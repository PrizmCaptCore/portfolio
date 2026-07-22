# B2B 멱등 프로비저닝 커맨드 (accounts/management/commands)
# 포트폴리오용으로 sanitize 되었습니다: 내부 endpoint/키/제품 특정 내용 제거.

import csv
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.core.exceptions import ValidationError

from apps.accounts.password_reset import (
    build_react_password_reset_url,
    send_password_reset_email,
)
from apps.teams.models import Membership, Role, Team


class Command(BaseCommand):
    help = "이메일 리스트로 B2B 계정을 일괄 생성하고 비밀번호 재설정 정보를 처리합니다."

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            required=True,
            help="이메일 목록 파일 경로(.txt/.csv).",
        )
        parser.add_argument(
            "--send-reset-email",
            action="store_true",
            help="생성/기존 계정 모두에 비밀번호 재설정 메일을 발송합니다.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="실제 생성/메일 발송 없이 결과만 출력합니다.",
        )
        parser.add_argument(
            "--export-reset-links",
            default="b2b_reset_links.csv",
            help=(
                "계정별 비밀번호 재설정 링크 CSV 출력 경로. "
                "기본값: ./b2b_reset_links.csv"
            ),
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"]).expanduser()
        send_reset_email = options["send_reset_email"]
        dry_run = options["dry_run"]
        export_reset_links = (options.get("export_reset_links") or "").strip()
        export_path = Path(export_reset_links).expanduser() if export_reset_links else None

        if not file_path.exists():
            raise CommandError(f"파일을 찾을 수 없습니다: {file_path}")

        rows = self._extract_rows(file_path)
        if not rows:
            self.stdout.write(self.style.WARNING("유효한 이메일이 없습니다."))
            return

        User = get_user_model()
        created_count = 0
        existed_count = 0
        reset_sent_count = 0
        membership_created_count = 0
        membership_existed_count = 0
        membership_skipped_count = 0
        reset_rows = []

        for row in rows:
            email = row["email"]
            team_uuid = row.get("team_uuid")
            user = User.objects.filter(email__iexact=email).first()
            created = False

            if user is None:
                if dry_run:
                    self.stdout.write(f"[DRY-RUN] create: {email}")
                else:
                    user = User.objects.create_user(email=email, password=None)
                    user.set_unusable_password()
                    user.save(update_fields=["password"])
                    self.stdout.write(self.style.SUCCESS(f"created: {email}"))
                created = True
            else:
                existed_count += 1
                self.stdout.write(f"exists: {user.email}")

            if created:
                created_count += 1

            membership_note = ""
            if team_uuid:
                team = Team.objects.filter(uuid=team_uuid).first()
                if team is None:
                    membership_note = f"team_uuid_not_found:{team_uuid}"
                    self.stderr.write(
                        self.style.WARNING(f"skip_membership_team_not_found: {email} ({team_uuid})")
                    )
                    membership_skipped_count += 1
                elif not team.has_available_seat():
                    membership_note = f"team_no_available_seat:{team_uuid}"
                    self.stderr.write(
                        self.style.WARNING(f"skip_membership_no_seat: {email} ({team_uuid})")
                    )
                    membership_skipped_count += 1
                elif dry_run:
                    self.stdout.write(f"[DRY-RUN] add_membership: {email} -> {team_uuid}")
                    membership_created_count += 1
                else:
                    membership, was_created = Membership.objects.get_or_create(
                        user=user,
                        team=team,
                        defaults={"role": Role.MEMBER},
                    )
                    if was_created:
                        self.stdout.write(f"membership_created: {email} -> {team.uuid}")
                        membership_created_count += 1
                    else:
                        self.stdout.write(f"membership_exists: {email} -> {team.uuid}")
                        membership_existed_count += 1

                    # 신규 계정의 경우, current_team이 비어 있으면 지정한 팀으로 세팅
                    if created:
                        profile = getattr(user, "profile", None)
                        should_set_current_team = (
                            profile is not None
                            and getattr(profile, "current_team_id", None) is None
                        )
                        if should_set_current_team:
                            profile.current_team = team
                            profile.save(update_fields=["current_team"])

            if send_reset_email:
                if dry_run:
                    self.stdout.write(f"[DRY-RUN] send_reset: {email}")
                    reset_sent_count += 1
                else:
                    try:
                        send_password_reset_email(user)
                        self.stdout.write(f"reset_sent: {user.email}")
                        reset_sent_count += 1
                    except Exception as exc:
                        self.stderr.write(self.style.ERROR(f"reset_failed: {email} ({exc})"))

            reset_link = ""
            link_note = ""
            if user is not None:
                reset_link = build_react_password_reset_url(user)
            elif dry_run:
                link_note = "dry-run으로 신규 계정 링크 미생성"

            reset_rows.append(
                {
                    "email": email,
                    "created": "yes" if created else "no",
                    "reset_link": reset_link,
                    "note": ", ".join([n for n in (link_note, membership_note) if n]),
                }
            )

        if export_path:
            export_path.parent.mkdir(parents=True, exist_ok=True)
            self._write_reset_links_csv(export_path, reset_rows)
            self.stdout.write(self.style.SUCCESS(f"재설정 링크 파일: {export_path}"))

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("완료"))
        self.stdout.write(f"- 총 이메일: {len(rows)}")
        self.stdout.write(f"- 신규 생성: {created_count}")
        self.stdout.write(f"- 기존 계정: {existed_count}")
        self.stdout.write(f"- 재설정 메일 발송: {reset_sent_count}")
        self.stdout.write(f"- 팀 소속 추가(신규): {membership_created_count}")
        self.stdout.write(f"- 팀 소속 이미 존재: {membership_existed_count}")
        self.stdout.write(f"- 팀 소속 스킵: {membership_skipped_count}")

    def _extract_rows(self, file_path: Path):
        seen = set()
        valid_rows = []

        if file_path.suffix.lower() == ".csv":
            with file_path.open("r", encoding="utf-8-sig", newline="") as csvfile:
                reader = csv.DictReader(csvfile)
                if not reader.fieldnames:
                    raise CommandError("CSV 헤더를 찾을 수 없습니다.")
                email_field = self._pick_email_field(reader.fieldnames)
                if not email_field:
                    raise CommandError("CSV에 email 컬럼이 필요합니다.")
                team_uuid_field = self._pick_team_uuid_field(reader.fieldnames)
                for row in reader:
                    email = self._normalize_and_validate_email(row.get(email_field))
                    if not email or email in seen:
                        continue

                    team_uuid = (row.get(team_uuid_field) if team_uuid_field else "") or ""
                    team_uuid = team_uuid.strip() or None

                    seen.add(email)
                    valid_rows.append({"email": email, "team_uuid": team_uuid})
            return valid_rows

        with file_path.open("r", encoding="utf-8-sig") as fp:
            for raw_line in fp:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                for token in line.split(","):
                    email = self._normalize_and_validate_email(token)
                    if not email or email in seen:
                        continue
                    seen.add(email)
                    valid_rows.append({"email": email, "team_uuid": None})

        return valid_rows

    def _pick_email_field(self, field_names):
        lowered = {name.strip().lower(): name for name in field_names}
        for candidate in ("email", "e-mail", "mail"):
            if candidate in lowered:
                return lowered[candidate]
        return None

    def _pick_team_uuid_field(self, field_names):
        lowered = {name.strip().lower(): name for name in field_names}
        for candidate in ("team_uuid", "team", "team id", "team_id"):
            if candidate in lowered:
                return lowered[candidate]
        return None

    def _normalize_and_validate_email(self, email):
        normalized = (email or "").strip().lower()
        if not normalized:
            return
        try:
            validate_email(normalized)
        except ValidationError:
            self.stderr.write(self.style.WARNING(f"skip_invalid_email: {email}"))
            return
        return normalized

    def _write_reset_links_csv(self, export_path: Path, rows):
        with export_path.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.DictWriter(
                fp,
                fieldnames=["email", "created", "reset_link", "note"],
            )
            writer.writeheader()
            writer.writerows(rows)
