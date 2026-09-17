# Orthanc + openEHR(EHRbase) 통합 — 가명화 브리지

> 영상(DICOM)은 [Orthanc](https://www.orthanc-server.com), 임상 기록은 [openEHR](https://openehr.org/platform/)
> 표준 CDR(EHRbase)에 두고, 둘 사이를 **하나의 가명화·비식별화 정책**으로 잇는 통합 레포.
> 식별 가능한 데이터는 source Orthanc 밖으로 나가지 않고, 연구·ML·openEHR 이 접근하는 것은
> 모두 가명화된 사본이다.

```text
 modality ──C-STORE──▶ orthanc (identified)          ehrbase (openEHR CDR)
                          │ /changes: StableStudy        ▲  EHR(subject = pseudonym) + composition
                          ▼                              │  (dates shifted, WADO-RS link only)
                     integration ── de-identify ──▶ orthanc-deid ──DICOMweb──▶ consumers
                          │
                          └── reident vault (sqlite, 별도 보호 스토리지)
```

## 구성

```text
.
├── docker-compose.yml        # orthanc + orthanc-deid (각각 PostgreSQL), ehrbase + ehrbase-db, integration
├── .env.example              # 비밀번호·HMAC 키·subject namespace
├── orthanc/orthanc.json      # source Orthanc 사이트 설정 (DICOMweb, 로그 비식별화)
├── templates/                # openEHR OPT (imaging_study_summary) — Archetype Designer 로 생성, README 참고
└── integration/              # Python 브리지 (pip install -e ., 콘솔 명령 hci)
    ├── Dockerfile, pyproject.toml
    ├── src/healthcare_integration/
    │   ├── config.py             # 환경변수 → Settings (pydantic-settings)
    │   ├── orthanc_client.py     # /changes 팔로우, /tools/find, /instances 전송, WADO-RS URL
    │   ├── openehr_client.py     # 템플릿 업로드, subject 기준 EHR 생성/조회, FLAT composition, AQL
    │   ├── deid/
    │   │   ├── pseudonymizer.py  # HMAC 가명 + 환자별 날짜 시프트 + UID 재매핑 + 재식별 vault
    │   │   ├── dicom_deid.py     # PS3.15 Basic Profile + 날짜 보존(시프트) + 환자 특성 보존, 번인 텍스트 격리
    │   │   └── openehr_deid.py   # FLAT composition 에 같은 가명/시프트 적용 + 자유 텍스트 정규식 redaction
    │   ├── pipeline.py           # StableStudy → 비식별화 → orthanc-deid → EHR 보장 → composition
    │   └── cli.py                # hci watch|once|deid-file|reident|aql|demo
    └── tests/test_deid.py        # 서버 없이 도는 비식별화 테스트
```

## 왜 이렇게 설계했나

- **Orthanc 를 둘로 나눈다.** 같은 이미지지만 DB 가 다르다. 식별 데이터는 `orthanc` 에만 있고, `orthanc-deid` 는
  DICOM 수신(`DicomAlwaysAllowStore=false`)을 막아 브리지만 REST 로 쓴다. 연구자·ML 파이프라인·openEHR 은 8043 만 본다.
- **비식별화 정책은 코드 한 곳에.** Orthanc 의 내장 `/anonymize` 는 쓰지 않는다. DICOM 과 openEHR 이 **같은 `Pseudonymizer`**
  를 쓰기 때문에 한 환자가 두 시스템에서 같은 가명(`PSN-…`)과 같은 날짜 오프셋을 받는다. 그래서 EHRbase 의 composition 날짜와
  DICOM StudyDate 가 서로 맞고, 6개월 추적 검사 간격 같은 종단 정보가 살아남는다(PS3.15 "Retain Longitudinal Temporal Information with Modified Dates").
- **가명은 키 있는 HMAC.** 결정적이라 재수신·재실행에 안전하고, 키 없이는 id 공간을 열거할 수 없다. UID 도 같은 방식으로 재매핑해
  스터디 안의 모든 인스턴스가 일관되지만 원본 PACS 와는 조인되지 않는다.
- **가명화와 익명화의 차이는 vault 유무뿐.** `reident` 테이블(sqlite, 별도 보호 스토리지)을 남기면 우연한 소견(incidental finding)
  통보 경로가 열린 가명화, 남기지 않으면 익명화다. 코드 경로는 같다.
- **StableStudy 이벤트만 처리한다.** Orthanc 의 `/changes` 를 팔로우해 `StableAge` 동안 새 인스턴스가 없는 스터디만 집는다.
  반쯤 도착한 스터디를 절반만 비식별화하는 일이 없다. 커서를 저장해 재시작 시 이어서 처리하고, 재매핑된 StudyInstanceUID 로
  선조회해 멱등하다.
- **번인 텍스트는 격리한다.** `BurnedInAnnotation=YES` 또는 US/XA/SC 처럼 픽셀에 글자를 굽는 모달리티는 스터디 전체를 보류한다.
  헤더만 지운 초음파 캡처는 비식별화된 것이 아니다.
- **openEHR 은 subject 를 EHR 에만 둔다.** `EHR_STATUS.subject.external_ref = {namespace, PSN}` 으로 EHR 을 만들고
  EHRbase 의 (namespace, id) 유일성에 기대 "가명 환자 1명 = EHR 1개"를 보장한다. composition 은 FLAT JSON 으로 올리고,
  이미지로 돌아가는 유일한 링크는 `orthanc-deid` 의 WADO-RS URL 이다.
- **자유 텍스트 redaction 은 백스톱이다.** 전화번호·이메일·주민번호·"Dr. Name" 정규식은 구조화되지 않은 서술을 안전하게 만들지
  못한다. 경고를 남기고 사람 또는 임상 NER 검토로 넘긴다.

## 실행

```bash
cp .env.example .env            # DEID_SECRET 은 python -c "import secrets; print(secrets.token_hex(32))"
docker compose up -d
docker compose exec integration hci demo        # pydicom 샘플 CT 를 source Orthanc 에 업로드
docker compose logs -f integration               # StableStudy → 비식별화 → EHRbase composition 로그
```

- Orthanc(식별) `http://localhost:8042`, Orthanc(가명) `http://localhost:8043`, EHRbase `http://localhost:8080/ehrbase/swagger-ui/index.html`
- 조회: `docker compose exec integration hci aql "SELECT e/ehr_id/value, c/uid/value FROM EHR e CONTAINS COMPOSITION c"`
- 재식별(권한자): `hci reident PSN-XXXXXXXXXXXX`
- 서버 없이 파일 하나만: `DEID_SECRET=… hci deid-file in.dcm out.dcm`
- 테스트: `cd integration && pip install -e ".[dev]" && pytest`

`templates/imaging_study_summary.opt` 는 Archetype Designer 로 만들어 넣는다(`templates/README.md`). 데이터·OPT·vault 는 포함하지 않는다.

**Technologies**: Orthanc (DICOMweb, PostgreSQL 플러그인), EHRbase (openEHR REST, AQL, FLAT), pydicom, httpx, pydantic-settings, Docker Compose
