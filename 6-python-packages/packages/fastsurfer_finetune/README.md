# fastsurfer-finetune — FreeSurfer 를 기준으로 FastSurfer 를 비교·선별·파인튜닝

> 원본 코드는 퇴사 후 접근이 불가해 남아 있지 않다. 당시 구조(FastSurfer 출력을 FreeSurfer recon-all 출력과
> 비교 → 불일치 케이스 선별 → FastSurferCNN 파인튜닝 → 재평가)를 기억과 FastSurfer 공개 레포의 인터페이스에 맞춰
> 재구성한 **스케치**다. 실행 가능한 형태로 썼지만 임계값·에폭 등 수치는 당시 값이 아니라 합리적 기본값이다.

## 왜 이 구조였나

FreeSurfer recon-all 은 한 명에 6~10시간, FastSurfer 는 1분이다. 그런데 특정 스캐너·연령대에서 FastSurfer 가
해마·편도체 같은 작은 구조를 체계적으로 다르게 그렸다. 전체 재학습은 데이터가 부족했고(불일치 케이스 수십 명),
FreeSurfer 를 무조건 정답으로 쓰기도 위험했다(recon-all 도 실패한다). 그래서

1. **compare** — 두 출력을 구조별 Dice · 부피차(%) · HD95 로 채점한다. 피질 라벨은 뺀다. FreeSurfer 피질은 surface 기반이라
   볼륨 CNN 이 못 맞추는 게 정상이고, 그 불일치는 "CNN 이 틀렸다"는 신호가 아니다.
2. **select** — 테스트 셋을 **먼저** 사이트별 층화로 떼고, 남은 풀에서 hard(임계 미만) / easy(일치) 를 나눈다.
   hard 는 사람이 QC CSV 에 `pass` 를 찍은 경우에만 FreeSurfer 를 라벨로 쓴다. easy 를 hard 의 절반만큼 섞어 넣는 이유는
   이미 맞히던 케이스에서 드리프트하는 것을 막기 위해서다.
3. **finetune** — 공개 체크포인트(`aparc_vinn_{plane}_v2.0.0.pkl`)에서 시작해 plane 별로 파인튜닝한다.
   앞 3 epoch 은 encoder 를 고정하고 decoder 만, 이후 전체를 lr/5 로. loss 는 FastSurfer 의 CombinedLoss(가중 CE + Dice),
   가중치 마스크는 FastSurfer 의 median-frequency × edge 레시피를 그대로 쓴다. 조기 종료 기준은 loss 가 아니라
   **subcortical 평균 Dice** — loss 는 백질에서 계속 떨어지지만 작은 구조는 그보다 훨씬 먼저 멈춘다.
4. **evaluate** — 슬라이스 단위가 아니라 FastSurfer 의 `run_prediction.py` 로 3-plane soft voting 까지 돌린 3D 결과를
   step 1 과 같은 지표로 다시 채점한다. before/after 표에서 해마가 좋아져도 easy 케이스의 뇌실이 나빠지면 리뷰 탈락이다.

## 구성

```text
fastsurfer_finetune/
├── labels.py     # 채점 대상 subcortical LUT id, FastSurfer 클래스 매핑은 FASTSURFER_HOME 의 data_utils 에서 가져옴
├── compare.py    # Dice / 부피차 / HD95 (scipy EDT), per_structure.csv + per_subject.csv
├── select.py     # 층화 테스트 분리 → hard/easy → QC 게이트 → split.json
├── dataset.py    # orig.mgz + aseg.mgz → 7-채널 thick slice HDF5 (FastSurferCNN/generate_hdf5.py 와 같은 레이아웃)
├── finetune.py   # 체크포인트 로드(strict 키 검사), encoder freeze 단계, CombinedLoss, run_prediction 호환 저장
├── evaluate.py   # run_prediction.py 실행 + before/after 표
└── cli.py        # fsf-compare / fsf-select / fsf-finetune / fsf-evaluate
```

## 사용

```bash
export FASTSURFER_HOME=/opt/FastSurfer          # 공개 레포 체크아웃 (FastSurferCNN/ 필요)
pip install -e packages/fastsurfer_finetune

fsf-compare  --subjects subjects.txt --fastsurfer /data/fastsurfer --freesurfer /data/recon --out report/
fsf-select   --report report/ --qc qc.csv --site sites.csv --out split.json
for p in axial coronal sagittal; do
  fsf-finetune --split split.json --t1 /data/recon --freesurfer /data/recon --plane $p --config ft_$p.yaml
done
fsf-evaluate --split split.json --t1 /data/recon --freesurfer /data/recon --stock /data/fastsurfer \
             --ckpt-axi runs/finetune/axial_best.pkl --ckpt-cor runs/finetune/coronal_best.pkl \
             --ckpt-sag runs/finetune/sagittal_best.pkl --out report/eval
```

MRI 데이터·체크포인트·QC 표는 포함하지 않는다.

**Technologies**: FastSurfer (FastSurferVINN), FreeSurfer, nibabel, scipy, PyTorch, h5py, pandas
