## ⚙️ 사전 준비 프로그램
팀원들이 프로젝트를 실행하기 위해 필요한 프로그램들:

1. **Windows Subsystem for Linux 2 (WSL2)**
   - Microsoft Store에서 Ubuntu 설치
   - 최신 버전으로 업데이트 필요

2. **Docker Desktop**
   - Windows에서 실행
   - WSL2 기반으로 동작
   - NVIDIA Container Toolkit 연동 필요

3. **NVIDIA GPU 드라이버**
   - CUDA 지원 GPU 환경 필요
   - `nvidia-smi`로 정상 작동 확인

4. **Python 3.10+**
   - `requests`, `openai` 패키지 설치 필요

  ---------------------------------------------
## 팀원용 MySQL 설치 & DB 세팅 가이드
1. MySQL 설치
Windows

MySQL Installer
 다운로드

설치 시 Server Only 또는 Developer Default 선택

root 계정 비밀번호 설정 (꼭 기억하기!)

Mac

Homebrew로 설치:

brew install mysql


서비스 시작:

brew services start mysql


root 계정 보안 설정 실행:

mysql_secure_installation


VALIDATE PASSWORD: n (비밀번호 규칙 강제 안 함, 팀 작업 편리함)

root 비밀번호 새로 입력 → 꼭 기억하기

익명 사용자 삭제: y

원격 root 접속 차단: y

test DB 삭제: y

권한 새로고침: y

2. MySQL 접속
mysql -u root -p


👉 위 명령 실행 후 비밀번호 입력하면 MySQL 콘솔 접속됨.

3. 데이터베이스 생성
CREATE DATABASE dmu CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;

4. SQL 파일 불러오기

(같은 폴더에 dmu.sql 파일이 있다고 가정)

Windows (PowerShell / CMD)
mysql -u root -p dmu < dmu.sql

Mac (터미널)
mysql -u root -p dmu < dmu.sql

5. 확인

MySQL 접속 후:

USE dmu;
SHOW TABLES;


👉 테이블이 보이면 성공 ✅

6. 팀원 공통 주의사항

root 비밀번호를 잊지 말 것

DB 이름은 반드시 dmu

SQL 불러오기 전에 DB가 생성돼 있어야 함

dmu.sql 파일은 최신 버전을 공유해서 동일하게 맞출 것
