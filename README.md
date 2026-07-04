# reserve_page

호스트가 예약을 관리하는 소규모 숙소용 페이지 — 공개 달력 + 관리자 UI.

## 기능

- **공개 메인 페이지** (`/`) — 월별 달력에 각 객실의 빈 방(파랑) / 예약(빨강) 표시
- **관리자 로그인** (`/login`) — 오른쪽 상단 버튼
- **관리자 예약 달력** (`/reservations/calendar`) — 날짜 클릭 시 모달로 새 예약 등록
- **관리자 예약 리스트** (`/reservations`) — 필터 · 수정 · 취소 · 삭제
- 확정 예약 기간 겹침 자동 차단

## 로컬 실행 (SQLite)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
# → http://127.0.0.1:5000
# 첫 실행 시 3개 객실 시드 + 관리자 계정(admin / admin1234) 자동 생성
```

관리자 계정은 환경 변수로 바꿀 수 있습니다.
```bash
ADMIN_USER=host ADMIN_PASS=secret .venv/bin/python app.py
```

## Vercel 무료 배포

Vercel은 서버리스라 SQLite 파일이 유지되지 않습니다. 무료 Postgres(Neon)를 함께 씁니다.

### 1) 코드 준비 (완료)
- `api/index.py` — Vercel Python 진입점
- `vercel.json` — 라우팅
- `runtime.txt` — Python 3.12 지정
- `requirements.txt` — `psycopg2-binary` 포함

### 2) GitHub에 푸시
```bash
git init && git add . && git commit -m "initial"
git remote add origin https://github.com/<you>/reserve_page.git
git push -u origin main
```

### 3) Vercel 프로젝트 생성
1. <https://vercel.com/new> 에서 위 GitHub 저장소 Import
2. **Framework Preset: Other**, Root Directory 기본값 그대로

### 4) Neon Postgres 연결 (Vercel Marketplace)
1. 프로젝트 → **Storage** → **Create Database** → **Neon (Postgres)**
2. Free 플랜 선택 → 프로젝트에 연결
3. `DATABASE_URL` 환경 변수가 자동으로 주입됨

### 5) 환경 변수 추가 (Project → Settings → Environment Variables)
| 이름 | 값 |
| --- | --- |
| `SECRET_KEY` | 랜덤 문자열 (예: `python -c "import secrets; print(secrets.token_hex(32))"`) |
| `ADMIN_USER` | 원하는 관리자 아이디 |
| `ADMIN_PASS` | 강력한 비밀번호 |

### 6) Redeploy
Deployments 탭에서 **Redeploy** 누르면 첫 요청 때 자동으로:
- 테이블 생성
- 3개 객실(101호/201호/202호) 시드
- `ADMIN_USER`/`ADMIN_PASS` 로 관리자 계정 생성

배포된 URL(예: `reserve-page.vercel.app`)로 접속 → 우상단 **관리자 로그인**.

### 참고
- 관리자를 다시 만들려면 Neon 콘솔에서 `admin` 테이블을 비우고 재배포하면 됩니다.
- Neon Free 플랜: 512MB 스토리지 · 자동 정지 후 재시작 (첫 요청 시 1~2초 지연 가능).
