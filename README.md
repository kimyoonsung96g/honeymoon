# 신혼여행 호텔 가격 자동 추적

GitHub가 매일 오전 9시에 부킹닷컴 가격을 자동으로 조회하고, 결과를 휴대폰에서 볼 수 있는 페이지로 보여줍니다. PC는 꺼져 있어도 됩니다.

## 처음 한 번만 설정 (PC에서 약 10분)

1. github.com 가입 후 오른쪽 위 **+ → New repository**
   - 이름: `honeymoon` / **Public** 선택 / Create
2. **Add file → Upload files**에서 `check_prices.py`, `README.md`, `docs` 폴더를 끌어다 놓고 Commit
3. **Add file → Create new file**
   - 파일 이름 칸에 `.github/workflows/track.yml` 입력
   - `track.yml` 내용을 그대로 붙여넣고 Commit
4. **Settings → Pages**
   - Source: Deploy from a branch / Branch: `main`, 폴더: `/docs` → Save
   - 1~2분 뒤 나오는 주소(`https://kimyoonsung96g.github.io/honeymoon/`)를 휴대폰 홈 화면에 추가
5. **Actions 탭 → 호텔 가격 추적 → Run workflow**로 첫 조회 실행 (이후 매일 자동)

## 가격 하락 알림 받기 (선택)

1. 휴대폰에 **ntfy** 앱 설치 → + 눌러서 남이 추측하기 어려운 이름으로 구독 (예: `yoonsung-honeymoon-8231`)
2. GitHub 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `NTFY_TOPIC` / Secret: 위에서 정한 이름
3. 가격이 3만 원 이상 내려가면 휴대폰으로 알림이 옵니다.
