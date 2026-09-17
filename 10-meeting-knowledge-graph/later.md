전부 객체화 X. Who/What-주제(/Where)만 엔티티, Why/conflict는 사건↔사건 엣지, When/How는 속성.

## 새 DNA

load-bearing한 사건·엔티티·중요관계는 1급 객체, 불확실하면 임시→명시적 확정. 값싼 링크(belongs-to/시간)는 엣지 유지.

## Later 할 일

- `conflict.py:22` decision 하드코딩 → 충돌가능 타입 집합(설정)으로 일반화 (프롬프트 포함)
- `actor` 문자열 → Person 엔티티 승격. anonymous는 표면형별 고유 uuid(공유 null 금지), 팀 바인딩 시 소급 해소
- Why/Conflict만 객체로 reify(근거·confidence 품게), belongs-to/시간은 엣지
- Topic 엔티티는 Person 검증 후
