# 회의 요약·인텐트 LLM 파인튜닝 (unsloth LoRA SFT → vLLM 서빙)

> AI 회의 인텔리전스 제품 **Relay**(제품명 가명화)의 요약/인텐트 모델을 만든 학습 파이프라인의 **스케치**.
> 원본 학습 코드는 다른 작업 머신에 있었고 현재 남아 있지 않아, 서빙 코드([8-vllm-gpu-serving](../8-vllm-gpu-serving/))가
> 요구하는 입출력 계약과 당시 설계를 기준으로 재구성했다. 실행 가능한 형태로 썼지만 하이퍼파라미터와 데이터 스키마는
> 당시 값을 기억에 의존해 복원한 것이다.

## 왜 파인튜닝했나

서빙 워커(`runpod_inference`)는 회의 중 실시간으로 "지금까지의 요약 + 다음 액션 인텐트" 를 **엄격한 JSON** 으로 돌려줘야 한다.
기성 instruct 모델은 (1) 한국어/영어 code-switching 회의록에서 영어 용어를 한글로 음차하고, (2) JSON 바깥에 사족을 붙이고,
(3) 2B 급에서는 인텐트 분류가 흔들렸다. 프롬프트로 세 가지를 동시에 잡는 것보다 **작은 모델을 SFT 로 계약에 묶는 쪽**이
비용(always-on L4 한 대)과 지연 모두에서 나았다.

## 파이프라인

```text
회의록 청크 + 사람이 검수한 요약/인텐트 (JSONL)
        │  build_dataset.py   # 청크 슬라이딩, 스키마 검증, 중복 제거, 채팅 템플릿 적용, train/val 분리
        ▼
unsloth FastLanguageModel (Gemma 4 E2B-it, 4-bit 로드) + LoRA r=16
        │  train_sft.py       # TRL SFTTrainer, assistant 턴만 loss (completion-only), 2~3 epoch
        ▼
LoRA 어댑터 → merge_and_unload → 16-bit safetensors
        │  export_vllm.py     # vLLM 이 그대로 읽는 HF 디렉터리, 토크나이저/채팅 템플릿 동봉
        ▼
eval_contract.py             # JSON 유효율 · 스키마 적합률 · 인텐트 정확도 · 라틴 용어 보존율 → 합격 게이트
        ▼
runpod_inference Dockerfile 의 SUMMARY_MODEL 로 지정 (가중치는 이미지에 baking)
```

## 설계 결정

- **unsloth 를 쓴 이유**: 단일 소비자 GPU(24GB)에서 4-bit QLoRA 로 2B~4B 모델을 몇 시간 안에 돌릴 수 있고,
  `get_peft_model` 과 gradient checkpointing("unsloth" 모드)이 메모리를 절반 이하로 줄여 seq_len 4096 을 유지할 수 있었다.
- **completion-only loss**: 프롬프트(회의록) 토큰에는 loss 를 걸지 않는다. 회의록은 길고 요약은 짧아서, 전체 토큰에 loss 를 걸면
  모델이 회의록 재생산을 배운다.
- **JSON 을 데이터에서 강제**: 학습 타깃은 항상 `{"summary": ..., "intents": [...]}` 하나의 JSON 객체다.
  스키마에 안 맞는 라벨은 `build_dataset.py` 가 버린다. 서빙 쪽 정규식 후처리를 없애는 것이 목표였다.
- **라틴 용어 보존을 평가 게이트로**: 학습 데이터에 "AI, API, KPI, PR" 같은 용어를 한글 음차 없이 유지한 라벨만 넣고,
  `eval_contract.py` 가 보존율을 따로 잰다. 한국어 STT 프로젝트([9](../9-korean-asr-training/))와 같은 기준이다.
- **merge 해서 내보낸다**: vLLM 의 LoRA 서빙 대신 16-bit 로 병합해 단일 모델로 서빙. 어댑터 핫스왑이 필요 없었고,
  이미지에 가중치를 굽는 서빙 설계와 맞물린다.

## 실행

```bash
pip install "unsloth[cu121-torch240]" trl datasets

python build_dataset.py --raw data/labeled_meetings.jsonl --out data/sft --max-tokens 3500
python train_sft.py --data data/sft --base google/gemma-4-E2B-it --out runs/summary-lora --epochs 2
python export_vllm.py --base google/gemma-4-E2B-it --lora runs/summary-lora --out runs/summary-merged
python eval_contract.py --model runs/summary-merged --data data/sft/val.jsonl
```

데이터와 가중치는 포함하지 않는다. 라벨 데이터는 사내 회의록이라 공개할 수 없다.

**Technologies**: unsloth, TRL SFTTrainer, PEFT/LoRA, bitsandbytes 4-bit, Gemma, vLLM 호환 export
