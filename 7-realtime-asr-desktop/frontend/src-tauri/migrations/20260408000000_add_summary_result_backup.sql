-- summary_processes 테이블에 result_backup / result_backup_timestamp 컬럼 추가.
-- 이 컬럼들은 summary 재생성(regenerate) 시 이전 결과를 백업해두기 위해 사용된다.
-- 코드(database/repositories/summary.rs)는 이미 이 컬럼을 참조하고 있었지만
-- initial schema에는 빠져 있어 "no such column: result_backup" 에러가 발생했다.
ALTER TABLE summary_processes ADD COLUMN result_backup TEXT;
ALTER TABLE summary_processes ADD COLUMN result_backup_timestamp TEXT;
