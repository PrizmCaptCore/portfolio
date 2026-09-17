# fastsurfer-finetune — FreeSurfer 를 기준으로 FastSurfer v1 을 비교·선별·파인튜닝

> 원본 코드는 퇴사 후 접근이 불가해 남아 있지 않다. 당시 구조(FastSurfer 출력을 FreeSurfer recon-all 출력과
> 비교 → 불일치 케이스 선별 → FastSurferCNN 파인튜닝 → 재평가)를 기억과 FastSurfer 공개 레포의 인터페이스에 맞춰
> 재구성한 **스케치**다. 기준 코드는 **FastSurfer v1(1.1.x) 의 `feature/one-shot-bias-field` 브랜치**(2022-05)이며,
> v2 의 VINN/config 체계가 아니라 v1 의 `FastSurferCNN(params)` · `Epoch_NN_training_state.pkl` · `eval.py` API 를 따른다.
> 임계값·에폭 등 수치는 당시 값이 아니라 합리적 기본값이다.

## 왜 이 구조였나

FreeSurfer recon-all 은 한 명에 6~10시간, FastSurfer 는 1분이다. 그런데 특정 스캐너·연령대에서 FastSurfer 가
해마·편도체 같은 작은 구조를 체계적으로 다르게 그렸고, 그 불일치는 **스캐너 shading(bias field)이 강한 곳**과 겹쳤다.
전체 재학습은 데이터가 부족했고(불일치 케이스 수십 명), FreeSurfer 를 무조건 정답으로 쓰기도 위험했다(recon-all 도 실패한다).

0. **preprocess** — 브랜치가 추가한 `recon_surf/bias_field_correction.py` 를 학습 입력 전처리로 끌어 쓴다.
   N4 를 반복 추정하는 대신 **CNN 세그를 조직 prior 로 Gaussian 클러스터(GM/WM/CSF/시상/…)를 잡고 DCT 기저로 bias field 를
   한 번에(one-shot) 적합**해 나눠 주고 WM 을 110 으로 정규화한다. 원래 recon-surf 단계에서 `orig_nu.mgz` 를 만드는 용도였는데,
   같은 보정을 학습 입력에도 적용하자 loss 를 손대는 것보다 해마 Dice 가 더 움직였다. FreeSurfer 산출물에 의존하지 않는다.
1. **compare** — 두 출력을 구조별 Dice · 부피차(%) · HD95 로 채점한다. 피질 라벨은 뺀다. FreeSurfer 피질은 surface 기반이라
   볼륨 CNN 이 못 맞추는 게 정상이고, 그 불일치는 "CNN 이 틀렸다"는 신호가 아니다.
2. **select** — 테스트 셋을 **먼저** 사이트별 층화로 떼고, 남은 풀에서 hard(임계 미만) / easy(일치) 를 나눈다.
   hard 는 사람이 QC CSV 에 `pass` 를 찍은 경우에만 FreeSurfer 를 라벨로 쓴다. easy 를 hard 의 절반만큼 섞는 이유는
   이미 맞히던 케이스에서 드리프트하는 것을 막기 위해서다.
3. **finetune** — HDF5 는 v1 의 `generate_hdf5.PopulationDataset` 로 그대로 만든다(`map_aparc_aseg2label` + no-CC 마스크,
   median-frequency × edge 가중치, 7-슬라이스 thick stack). 공개 체크포인트 `Epoch_30_training_state.pkl` 에서 시작해
   plane 별로 파인튜닝: 앞 3 epoch 은 `encode1..4 + bottleneck` 을 고정하고 decoder + classifier 만, 이후 전체를 lr/5 로.
   loss 는 v1 `CombinedLoss`(가중 CE + Dice). 조기 종료 기준은 loss 가 아니라 **subcortical 평균 Dice** — loss 는 백질에서
   계속 떨어지지만 작은 구조는 그보다 훨씬 먼저 멈춘다. 저장은 `Solver` 와 같은 키(`model_state_dict`)라 `eval.py` 가 바로 읽는다.
4. **evaluate** — 슬라이스가 아니라 v1 `eval.py` 의 3-plane view aggregation 까지 돌린 3D 결과를 step 1 과 같은 지표로 다시
   채점한다. before/after 표에서 해마가 좋아져도 easy 케이스의 뇌실이 나빠지면 리뷰 탈락이다.

## 구성

```text
fastsurfer_finetune/
├── labels.py      # 채점 대상 subcortical LUT id, v1 CLASS_NAMES 기반 subcortical 클래스 인덱스, FASTSURFER_HOME 경로 설정
├── preprocess.py  # reduce_to_aseg.py → bias_field_correction.py (--norm) → mri/orig_nu.mgz
├── compare.py     # Dice / 부피차 / HD95 (scipy EDT), per_structure.csv + per_subject.csv
├── select.py      # 층화 테스트 분리 → hard/easy → QC 게이트 → split.json
├── dataset.py     # v1 generate_hdf5.PopulationDataset 래퍼 (image_name 만 선택: orig.mgz / orig_nu.mgz)
├── finetune.py    # FastSurferCNN(params) + Epoch_30 로드(strict), encoder freeze 단계, CombinedLoss, Solver 호환 저장
├── evaluate.py    # eval.py --network_{axial,coronal,sagittal}_path 실행 + before/after 표
└── cli.py         # fsf-preprocess / fsf-compare / fsf-select / fsf-finetune / fsf-evaluate
```

## 사용

```bash
git clone -b feature/one-shot-bias-field https://github.com/Deep-MI/FastSurfer /opt/FastSurfer
export FASTSURFER_HOME=/opt/FastSurfer                     # FastSurferCNN/ 와 recon_surf/ 를 sys.path 에 올림
pip install -e packages/fastsurfer_finetune

fsf-preprocess --subjects subjects.txt --fastsurfer /data/fastsurfer      # orig_nu.mgz 생성
fsf-compare    --subjects subjects.txt --fastsurfer /data/fastsurfer --freesurfer /data/recon --out report/
fsf-select     --report report/ --qc qc.csv --site sites.csv --out split.json
for p in axial coronal sagittal; do
  fsf-finetune --split split.json --freesurfer /data/recon --plane $p --config ft_$p.yaml
done
fsf-evaluate --split split.json --t1 /data/recon --freesurfer /data/recon --stock /data/fastsurfer \
             --ckpt-axi runs/finetune/axial/best_training_state.pkl \
             --ckpt-cor runs/finetune/coronal/best_training_state.pkl \
             --ckpt-sag runs/finetune/sagittal/best_training_state.pkl --out report/eval
```

`ft_<plane>.yaml` 은 `FinetuneConfig` 필드(`ckpt_in`, `out_dir`, `epochs`, `freeze_epochs`, `lr`, `batch_size`)를 덮어쓴다.
MRI 데이터·체크포인트·QC 표는 포함하지 않는다.

**Technologies**: FastSurfer v1 (FastSurferCNN, one-shot bias field), FreeSurfer, nibabel, scipy, PyTorch, h5py, pandas
