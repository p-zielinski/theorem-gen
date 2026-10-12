"""From-scratch transformer, about 50M parameters. Every weight is trained."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
from mlx.utils import tree_flatten, tree_merge, tree_unflatten

from theorem_gen.learn.minilm import END, PAD, VOCAB


@dataclass(frozen=True)
class LMConfig:
    n_layer: int
    d_model: int
    n_head: int
    context: int
    vocab: int = VOCAB


# 16 layers at width 512. A rich proof is at most about 250 tokens,
# so a context of 512 holds the role tag, the statement, and the tactics.
PRODUCTION = LMConfig(n_layer=16, d_model=512, n_head=8, context=512)
TINY = LMConfig(n_layer=1, d_model=32, n_head=4, context=32)


def parameter_count(config: LMConfig) -> int:
    d = config.d_model
    per_layer = (2 * d) + (12 * d * d)
    return config.vocab * d + config.n_layer * per_layer + d


class Block(nn.Module):
    def __init__(self, d_model: int, n_head: int) -> None:
        super().__init__()
        self.n1 = nn.RMSNorm(d_model)
        self.attn = nn.MultiHeadAttention(d_model, n_head, bias=False)
        self.n2 = nn.RMSNorm(d_model)
        self.up = nn.Linear(d_model, 4 * d_model, bias=False)
        self.down = nn.Linear(4 * d_model, d_model, bias=False)
        self.act = nn.GELU()

    def __call__(self, x, mask):
        y = self.n1(x)
        x = x + self.attn(y, y, y, mask=mask)
        y = self.n2(x)
        return x + self.down(self.act(self.up(y)))


class CausalLM(nn.Module):
    def __init__(self, config: LMConfig) -> None:
        super().__init__()
        self.embed = nn.Embedding(config.vocab, config.d_model)
        self.blocks = [Block(config.d_model, config.n_head) for _ in range(config.n_layer)]
        self.norm = nn.RMSNorm(config.d_model)

    def __call__(self, tokens):
        x = self.embed(tokens)
        mask = nn.MultiHeadAttention.create_additive_causal_mask(tokens.shape[1])
        for block in self.blocks:
            x = block(x, mask)
        return self.embed.as_linear(self.norm(x))


def count_arrays(model: nn.Module) -> int:
    from mlx.utils import tree_flatten

    return sum(array.size for _, array in tree_flatten(model.parameters()))


def loss_fn(model, tokens, lengths):
    logits = model(tokens)[:, :-1, :]
    targets = tokens[:, 1:]
    batch, steps, vocab = logits.shape
    token_loss = nn.losses.cross_entropy(
        logits.reshape(batch * steps, vocab),
        targets.reshape(batch * steps),
        reduction="none",
    ).reshape(batch, steps)
    index = mx.arange(steps)
    valid = ((index[None, :] + 1) < lengths[:, None]).astype(mx.float32)
    return (token_loss * valid).sum() / mx.maximum(valid.sum(), mx.array(1.0))


class Trainer:
    def __init__(self, config: LMConfig, lr: float = 3e-4) -> None:
        self.config = config
        self.model = CausalLM(config)
        self.optimizer = optim.AdamW(learning_rate=lr, weight_decay=0.01)
        self._grad = nn.value_and_grad(self.model, loss_fn)
        mx.eval(self.model.parameters())

    def step(self, rows: list, lengths: list) -> float:
        tokens = mx.array(rows, dtype=mx.int32)
        lens = mx.array(lengths, dtype=mx.int32)
        loss, grads = self._grad(self.model, tokens, lens)
        self.optimizer.update(self.model, grads)
        mx.eval(self.model.parameters(), self.optimizer.state, loss)
        return float(loss.item())

    def complete(self, prompt: list, max_new: int = 96) -> list:
        ids = list(prompt)
        for _ in range(max_new):
            window = ids[-self.config.context :]
            logits = self.model(mx.array([window], dtype=mx.int32))
            mx.eval(logits)
            nxt = int(mx.argmax(logits[0, -1]).item())
            ids.append(nxt)
            if nxt in {END, PAD}:
                break
        return ids

    def save(self, path, moments: bool = True) -> None:
        path = Path(path)
        self.model.save_weights(str(path))
        if not moments:
            return
        flat = {
            key: value
            for key, value in tree_flatten(self.optimizer.state)
            if isinstance(value, mx.array)
        }
        if "step" in flat:
            flat["step"] = flat["step"].astype(mx.uint32)
        if "embed.weight.m" not in flat:
            return
        dest = path.with_name("adam.safetensors")
        tmp = path.with_name("adam.saving.safetensors")
        try:
            mx.save_safetensors(str(tmp), flat)
            os.replace(tmp, dest)
        except Exception as exc:
            if tmp.exists():
                tmp.unlink()
            print(f"lm adam save failed: {exc}", flush=True)

    def load(self, path) -> None:
        path = Path(path)
        self.model.load_weights(str(path))
        mx.eval(self.model.parameters())
        adam = path.with_name("adam.safetensors")
        if not adam.is_file():
            return
        try:
            flat = dict(mx.load(str(adam)))
        except Exception:
            return
        if "embed.weight.m" not in flat:
            return
        if "step" in flat:
            flat["step"] = flat["step"].astype(mx.uint64)
        self.optimizer.init(self.model.trainable_parameters())
        loaded = tree_unflatten(list(flat.items()))
        self.optimizer.state = tree_merge(
            self.optimizer.state, loaded, merge_fn=lambda _current, saved: saved
        )
        mx.eval(self.optimizer.state)
