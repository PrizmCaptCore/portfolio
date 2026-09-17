"""Multi-head merge test: can the two trained NanoDets share one backbone as-is?

Both models are the same arch (ShuffleNetV2 1.5x + GhostPAN 128ch + NanoDetPlusHead),
trained separately: potato (1 class, epoch~35 best) and binary normal/abnormal
(2 classes, epoch~54 best). A shared-backbone multi-head model is therefore pure
state_dict splicing -- no new modules. What is NOT free is accuracy: each head was
calibrated to its own backbone's features. This script produces the checkpoints that
measure exactly that gap with nanodet's own evaluator, so the numbers are comparable
to the eval_results.txt the models were selected on:

    cd ai_part && python src/multihead_test.py            # splice + verify + timing
    python ~/workspace/nanodet/tools/test.py --task val \
        --config <cfg> --model runs/multihead_test/<name>.ckpt   # x4, see below

Outputs under runs/multihead_test/:
    potato-base.ckpt          original potato weights, rewrapped   (harness baseline)
    binary-base.ckpt          original binary weights, rewrapped   (harness baseline)
    potato-on-binaryBB.ckpt   potato head transplanted onto binary backbone+fpn
    binary-on-potatoBB.ckpt   binary head transplanted onto potato backbone+fpn
    multihead.pth             binary backbone+fpn + both heads, for the demo below
                              and as the init for recalibration training if needed

Checkpoint format: tools/test.py does task.load_state_dict(ckpt["state_dict"]) with
strict=True on a TrainingTask that holds both model.* and avg_model.* (weight_averager
is in the config), and its predict() runs self.model. The .pth files hold the EMA
weights (save_model_state saves weight_averager.state_dict()), which is also what the
baseline eval numbers were measured on. So: write the EMA-spliced weights into BOTH
model.* and avg_model.* slots and the comparison stays apples-to-apples.

The aux_fpn/aux_head weights ride along with whichever model owns the head: they are
training-only, but build_model() creates them, so strict loading needs shape-matching
tensors (aux num_classes tracks the head's).
"""
import os

import torch
import pytorch_lightning as pl

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(REPO, "runs")
OUT = os.path.join(RUNS, "multihead_test")

POTATO_PTH = os.path.join(RUNS, "nanodet_potato", "model_best", "nanodet_model_best.pth")
BINARY_PTH = os.path.join(RUNS, "nanodet_binary", "model_best", "nanodet_model_best.pth")
POTATO_CFG = os.path.join(REPO, "src", "config", "nanodet-plus-m-1.5x_416_potato.yml")
BINARY_CFG = os.path.join(REPO, "src", "config", "nanodet-plus-m-1.5x_416_binary.yml")

# What the two models can share: everything up to the FPN output. Heads, and the
# training-only aux modules calibrated to them, stay with their owner.
SHARED = ("backbone.", "fpn.")


def load_sd(path):
    return torch.load(path, map_location="cpu")["state_dict"]


def splice(head_sd, donor_sd):
    """Head owner's weights, except backbone/fpn taken from the donor."""
    out = {}
    for k, v in head_sd.items():
        if k.startswith(SHARED):
            assert donor_sd[k].shape == v.shape, f"shape mismatch at {k}"
            out[k] = donor_sd[k]
        else:
            out[k] = v
    return out


def to_lightning(sd):
    full = {f"model.{k}": v for k, v in sd.items()}
    full.update({f"avg_model.{k}": v for k, v in sd.items()})
    return {"state_dict": full, "pytorch-lightning_version": pl.__version__}


def main():
    os.makedirs(OUT, exist_ok=True)
    potato, binary = load_sd(POTATO_PTH), load_sd(BINARY_PTH)

    # If the two backbones had converged to near-identical weights the whole test
    # would be vacuous -- record how far apart they actually are.
    diffs = [(potato[k] - binary[k]).abs().mean().item()
             for k in potato if k.startswith(SHARED) and potato[k].dtype.is_floating_point]
    print(f"backbone+fpn mean |delta| between the two models: {sum(diffs) / len(diffs):.4f}")

    ckpts = {
        "potato-base": potato,
        "binary-base": binary,
        "potato-on-binaryBB": splice(potato, binary),
        "binary-on-potatoBB": splice(binary, potato),
    }
    for name, sd in ckpts.items():
        torch.save(to_lightning(sd), os.path.join(OUT, f"{name}.ckpt"))
        print(f"wrote {name}.ckpt")

    # The merged artifact: one backbone+fpn (binary donor -- it saw the harder task
    # and 2x the epochs), both heads keyed by task. This is the file a future
    # recalibration run or a two-headed ONNX export starts from.
    merged = {k: v for k, v in binary.items() if k.startswith(SHARED)}
    for prefix, sd in (("head_potato.", potato), ("head_binary.", binary)):
        merged.update({prefix + k: v for k, v in sd.items() if not k.startswith(SHARED)})
    torch.save({"state_dict": merged, "donor": "binary"}, os.path.join(OUT, "multihead.pth"))
    print("wrote multihead.pth")

    verify_and_time(ckpts)


def verify_and_time(ckpts):
    """Prove the shared-forward composition equals the spliced single models, then
    measure what sharing actually saves. 4070 laptop numbers are a proxy for Orin --
    the ratio transfers even though the absolute ms will not."""
    from nanodet.model.arch import build_model
    from nanodet.util import cfg as _cfg, load_config

    load_config(_cfg, POTATO_CFG)
    cfg_p = _cfg.clone()
    load_config(_cfg, BINARY_CFG)
    cfg_b = _cfg.clone()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    torch.backends.cudnn.benchmark = True

    def build(cfg_node, sd):
        m = build_model(cfg_node.model)
        m.load_state_dict(sd)
        return m.to(device).eval()

    m_binary = build(cfg_b, ckpts["binary-base"])
    m_potato_spliced = build(cfg_p, ckpts["potato-on-binaryBB"])
    m_potato_orig = build(cfg_p, ckpts["potato-base"])

    x = torch.randn(1, 3, 416, 416, device=device)

    with torch.no_grad():
        # Shared forward: donor backbone+fpn once, then each head on the same feats.
        feats = m_binary.fpn(m_binary.backbone(x))
        out_b = m_binary.head(feats)
        out_p = m_potato_spliced.head(feats)
        # Must match the spliced model run end-to-end -- same weights, same ops.
        ref_p = m_potato_spliced(x)
        ref_b = m_binary(x)
    err = max((out_p - ref_p).abs().max().item(), (out_b - ref_b).abs().max().item())
    print(f"shared-forward vs spliced-model max |delta|: {err:.2e}")
    assert err < 1e-4, "shared forward does not reproduce the spliced models"

    n_shared = sum(v.numel() for k, v in ckpts["binary-base"].items() if k.startswith(SHARED))
    n_head = sum(v.numel() for k, v in ckpts["binary-base"].items()
                 if k.startswith("head."))
    print(f"params: backbone+fpn {n_shared / 1e6:.2f}M shared, "
          f"{n_head / 1e6:.2f}M per extra head")

    def bench(fn, iters=200, warmup=20):
        with torch.no_grad():
            for _ in range(warmup):
                fn()
            if device.type == "cuda":
                torch.cuda.synchronize()
            import time
            t0 = time.time()
            for _ in range(iters):
                fn()
            if device.type == "cuda":
                torch.cuda.synchronize()
            return (time.time() - t0) / iters * 1000

    two_models = bench(lambda: (m_binary(x), m_potato_orig(x)))
    shared = bench(lambda: (lambda f: (m_binary.head(f), m_potato_spliced.head(f)))(
        m_binary.fpn(m_binary.backbone(x))))
    print(f"two full models: {two_models:.2f} ms   shared backbone + 2 heads: "
          f"{shared:.2f} ms   ({(1 - shared / two_models) * 100:.0f}% saved)")


if __name__ == "__main__":
    main()
