"""logger_singleton 검증 테스트.

검증 항목:
  T1  기본 동작      — 생성, 파일/콘솔 핸들러 부착, 파일에 1회 기록
  T2  싱글턴 동일성   — 두 번째 호출은 같은 인스턴스, 인자는 무시됨
  T3  반복 생성      — 여러 번 생성해도 핸들러가 쌓이지 않음 (항상 2개)
  T4  가드 방어      — 싱글턴이 뚫려도(이중 임포트 시뮬레이션) 핸들러 중복 없음
  T5  스레드 레이스   — 16개 스레드 동시 생성 → 인스턴스 1개, 핸들러 2개
  T6  propagate     — 루트 로거로 레코드가 새어나가지 않음 (콘솔 이중 출력 방지)
  T7  자식 로거      — getChild()로 모듈별 이름을 써도 기록은 1회

실행: python sketch_test/logger_test.py
"""
import logging
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common_part.logger_singleton import Logger, SingletonMeta

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  ({detail})" if detail and not cond else "") + "\n")
    if not cond:
        FAILURES.append(name)


def flush_handlers():
    for h in logging.getLogger('screening_logger').handlers:
        h.flush()


def count_in_file(path, needle):
    if not path.exists():
        return 0
    return path.read_text(encoding='utf-8').count(needle)


def reset_state():
    """싱글턴과 로깅 모듈 전역 상태를 초기화 (테스트 전용)."""
    lg = logging.getLogger('screening_logger')
    for h in list(lg.handlers):
        h.close()
        lg.removeHandler(h)
    SingletonMeta._instances.clear()


def main():
    tmpdir = Path(tempfile.mkdtemp(prefix="logger_test_"))
    log_file = tmpdir / "app.log"

    # ── T1: 기본 동작 ─────────────────────────────────────────────
    inst1 = Logger(log_file=str(log_file))
    log = inst1.get_logger()
    log.info("T1-marker")
    flush_handlers()
    check("T1 생성 및 파일 기록", count_in_file(log_file, "T1-marker") == 1,
          f"기록 횟수={count_in_file(log_file, 'T1-marker')}")
    check("T1 핸들러 2개(파일+콘솔)", len(log.handlers) == 2,
          f"핸들러 수={len(log.handlers)}")

    # ── T2: 싱글턴 동일성 + 인자 무시 ──────────────────────────────
    other_file = tmpdir / "other.log"
    inst2 = Logger(log_file=str(other_file))
    check("T2 같은 인스턴스 반환", inst1 is inst2)
    check("T2 두 번째 인자 무시(other.log 미생성)", not other_file.exists())

    # ── T3: 반복 생성해도 핸들러 불변 ─────────────────────────────
    for _ in range(10):
        Logger()
    log.info("T3-marker")
    flush_handlers()
    check("T3 핸들러 여전히 2개", len(log.handlers) == 2,
          f"핸들러 수={len(log.handlers)}")
    check("T3 중복 기입 없음", count_in_file(log_file, "T3-marker") == 1,
          f"기록 횟수={count_in_file(log_file, 'T3-marker')}")

    # ── T4: 싱글턴이 뚫린 상황에서 가드 방어 ───────────────────────
    SingletonMeta._instances.clear()          # 이중 임포트/리로드 시뮬레이션
    inst3 = Logger(log_file=str(tmpdir / "ignored.log"))
    check("T4 새 인스턴스 생성됨(싱글턴 뚫림 재현)", inst3 is not inst1)
    check("T4 그래도 핸들러 2개(가드 동작)", len(log.handlers) == 2,
          f"핸들러 수={len(log.handlers)}")
    inst3.get_logger().info("T4-marker")
    flush_handlers()
    check("T4 그래도 기록은 1회", count_in_file(log_file, "T4-marker") == 1,
          f"기록 횟수={count_in_file(log_file, 'T4-marker')}")

    # ── T5: 스레드 레이스 ─────────────────────────────────────────
    reset_state()
    race_file = tmpdir / "race.log"
    barrier = threading.Barrier(16)
    results = []

    def construct():
        barrier.wait()                        # 16개 스레드 동시 출발
        results.append(Logger(log_file=str(race_file)))

    threads = [threading.Thread(target=construct) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("T5 인스턴스 1개", len({id(r) for r in results}) == 1,
          f"인스턴스 수={len({id(r) for r in results})}")
    check("T5 핸들러 2개", len(results[0].get_logger().handlers) == 2,
          f"핸들러 수={len(results[0].get_logger().handlers)}")

    # ── T6: 루트 로거로 전파 차단 ─────────────────────────────────
    root_records = []

    class Counter(logging.Handler):
        def emit(self, record):
            root_records.append(record)

    counter = Counter()
    logging.getLogger().addHandler(counter)
    results[0].get_logger().info("T6-marker")
    logging.getLogger().removeHandler(counter)
    check("T6 루트로 전파 안 됨", len(root_records) == 0,
          f"루트 도달 레코드={len(root_records)}")

    # ── T7: 자식 로거로 모듈별 이름 ───────────────────────────────
    child = results[0].get_logger().getChild("camera_part")
    child.info("T7-marker")
    flush_handlers()
    check("T7 자식 로거도 기록 1회", count_in_file(race_file, "T7-marker") == 1,
          f"기록 횟수={count_in_file(race_file, 'T7-marker')}")
    check("T7 이름에 모듈 표시", count_in_file(race_file, "screening_logger.camera_part") == 1)

    if FAILURES:
        print(f"실패 {len(FAILURES)}건: {', '.join(FAILURES)} \n")
        sys.exit(1)
    print("전체 통과 \n")


if __name__ == "__main__":
    main()
