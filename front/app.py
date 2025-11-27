# ==========================================================
# app.py (Flask + MySQL + FastAPI RAG/STT/TTS 프록시 통합 + ChatLog 저장) - FINAL
# ==========================================================
import os
from pathlib import Path
from datetime import timedelta, datetime
from datetime import datetime, timedelta
from flask import Flask, jsonify, request, send_from_directory, session
from flask_cors import CORS
import mysql.connector
from dotenv import load_dotenv
import bcrypt
import requests
from dotenv import load_dotenv
import os


load_dotenv()  # ✅ .env 파일 읽기


# ----------------------------
# 1) 환경 변수 로드 (.env)
# ----------------------------
ENV_PATH = Path(__file__).with_name(".env")
load_dotenv(dotenv_path=ENV_PATH)

DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER", "root")
DB_PASS = os.getenv("DB_PASS", "")
DB_NAME = os.getenv("DB_NAME", "test")

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
PORT = int(os.getenv("PORT", "8001"))
FASTAPI_BASE = os.getenv("FASTAPI_BASE", "http://127.0.0.1:9000")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

print("==== ENV CHECK ====")
print("[ENV] DB_HOST =", DB_HOST)
print("[ENV] DB_NAME =", DB_NAME)
print("[ENV] FASTAPI_BASE =", FASTAPI_BASE)
print("====================")

# ----------------------------
# 2) Flask 초기화
# ----------------------------
app = Flask(__name__, static_folder="image", static_url_path="/image")
app.secret_key = SECRET_KEY
app.permanent_session_lifetime = timedelta(days=7)

# ✅ 세션 쿠키 설정 (iPhone/Safari 호환)
app.config.update(
    JSON_AS_ASCII=False,
    SESSION_COOKIE_SAMESITE="None",
    SESSION_COOKIE_SECURE=False
)

CORS(
    app,
    supports_credentials=True,
    origins=[
        "http://127.0.0.1:8001", 
        "http://localhost:8001",
        "http://192.168.43.138:8001"  # ⚡ 모바일 접속 주소
    ]
)


# ----------------------------
# 3) MySQL 연결
# ----------------------------
def get_raw_conn(database=None, autocommit=True):
    cfg = {
        "host": DB_HOST,
        "port": DB_PORT,
        "user": DB_USER,
        "password": DB_PASS or "",
        "database": database or None,
        "autocommit": autocommit,
        "auth_plugin": "mysql_native_password",
    }
    return mysql.connector.connect(**cfg)

def init_db():
    root = get_raw_conn(database=None)
    cur = root.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` DEFAULT CHARACTER SET utf8mb4")
    cur.close()
    root.close()

    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor()

    # users
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
          id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
          uid VARCHAR(64) UNIQUE NOT NULL,
          role VARCHAR(20) NOT NULL,
          name VARCHAR(100) NOT NULL,
          department VARCHAR(100) NOT NULL,
          email VARCHAR(150) NOT NULL,
          password_hash VARCHAR(200) NOT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # chat_logs
    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_logs (
          id INT AUTO_INCREMENT PRIMARY KEY,
          uid VARCHAR(64) NOT NULL,
          speaker ENUM('USER','BOT') NOT NULL,
          message TEXT NOT NULL,
          created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    # ✅ assignments (eClass 과제 테이블)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS assignments (
          id INT AUTO_INCREMENT PRIMARY KEY,
          subject_name VARCHAR(100) NOT NULL,
          title VARCHAR(255) NOT NULL,
          due_date DATETIME,
          status VARCHAR(20),
          score VARCHAR(20),
          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("[INIT_DB] ✅ OK (users + chat_logs + assignments)")

# ----------------------------
# 4) 유틸
# ----------------------------
def hash_pw(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def check_pw(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))

def save_chat(uid: str, speaker: str, message: str):
    """대화 로그 저장 (예외는 콘솔 경고만)"""
    try:
        if not (uid and message and speaker in ("USER", "BOT")):
            return
        conn = get_raw_conn(database=DB_NAME)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chat_logs(uid, speaker, message) VALUES(%s,%s,%s)",
            (uid, speaker, message[:5000]),
        )
        conn.commit()
    except Exception as e:
        print("[WARN] save_chat failed:", e)
    finally:
        try:
            cur.close()
            conn.close()
        except:
            pass

# ----------------------------
# 5) 회원가입 / 로그인 / 로그아웃 API
# ----------------------------
@app.post("/api/signup")
def signup():
    data = request.get_json(silent=True) or {}
    uid, role, name, dept, email, pw = (
        data.get("uid", "").strip(),
        data.get("role", "").strip(),
        data.get("name", "").strip(),
        data.get("dept", "").strip(),
        data.get("email", "").strip(),
        data.get("password", "").strip(),
    )
    if not all([uid, role, name, dept, email, pw]):
        return jsonify(ok=False, msg="필수 항목 누락"), 400

    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users(uid, role, name, department, email, password_hash) VALUES(%s,%s,%s,%s,%s,%s)",
            (uid, role, name, dept, email, hash_pw(pw)),
        )
        conn.commit()
        return jsonify(ok=True)
    except mysql.connector.errors.IntegrityError:
        return jsonify(ok=False, msg="이미 존재하는 아이디입니다."), 409
    finally:
        cur.close()
        conn.close()

@app.post("/api/login")
def login():
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    uid = (payload.get("uid") or payload.get("id") or "").strip()
    pw = (payload.get("password") or "").strip()
    if not uid or not pw:
        return jsonify(ok=False, msg="아이디/비밀번호 필요"), 400

    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)

    # 1️⃣ users 테이블 먼저 조회
    cur.execute("SELECT * FROM users WHERE uid=%s", (uid,))
    user = cur.fetchone()

    # 2️⃣ users에 없으면 student 테이블에서 조회
    if not user:
        cur.execute("""
            SELECT student_id AS uid, name, department, grade, status, pw AS plain_pw
            FROM student WHERE student_id=%s
        """, (uid,))
        student = cur.fetchone()

        if student:
            # student 테이블의 경우 pw는 평문
            if pw == student["plain_pw"]:
                session.update({
                    "uid": student["uid"],
                    "name": student["name"],
                    "department": student["department"],
                    "grade": student["grade"],
                    "status": student["status"],
                    "role": "student"
                })
                return jsonify(ok=True, user=session)
            else:
                return jsonify(ok=False, msg="비밀번호가 틀렸습니다."), 401
        else:
            return jsonify(ok=False, msg="존재하지 않는 사용자입니다."), 404

    # 3️⃣ users 로그인(bcrypt 해시 비교)
    import bcrypt
    if not bcrypt.checkpw(pw.encode('utf-8'), user["password_hash"].encode('utf-8')):
        return jsonify(ok=False, msg="비밀번호가 틀렸습니다."), 401

    session.update({
        "uid": user["uid"],
        "name": user["name"],
        "role": user["role"],
        "department": user["department"]
    })

    cur.close()
    conn.close()
    return jsonify(ok=True, user=user)

@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(ok=True)

@app.get("/api/me")
def me():
    if "uid" not in session:
        return jsonify(ok=False, msg="로그인 필요"), 401
    return jsonify(
        ok=True,
        user={
            "uid": session.get("uid"),
            "name": session.get("name"),
            "role": session.get("role"),
            "department": session.get("department"),
        },
    )

# ----------------------------
# 6) Flask → FastAPI 프록시 + 로그 저장
# ----------------------------
@app.post("/chat")
def proxy_chat():
    """프론트에서 /chat 로 주면 FastAPI(/rag/chat)로 포워딩 + 대화 저장"""
    payload = request.get_json(silent=True) or {}
    if "text" in payload:
        payload = {"query": (payload.get("text") or "").strip()}

    user_text = (payload.get("query") or "").strip()
    uid = session.get("uid", "guest")

    # 사용자 입력 저장
    if user_text:
        save_chat(uid, "USER", user_text)

    try:
        res = requests.post(f"{FASTAPI_BASE}/rag/chat", json=payload, timeout=60)
        data = res.json()
        bot_answer = (data.get("answer") or "").strip()
        # 봇 답변 저장
        if bot_answer:
            save_chat(uid, "BOT", bot_answer)
        return jsonify(data), res.status_code
    except Exception as e:
        return jsonify(ok=False, msg=f"RAG 서버 연결 실패: {e}"), 500

# ----------------------------
# 7) 대화 로그 조회 API (지난 7일 목록 / 특정일 상세)
# ----------------------------
@app.get("/api/chat/logs/7days")
def api_logs_7days():
    if "uid" not in session:
        return jsonify(ok=False, msg="로그인 필요"), 401
    uid = session["uid"]
    print("[DEBUG] current uid:", session.get("uid"))
    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)

    try:
        # 날짜별 로그 개수
        cur.execute(
            """
            SELECT DATE_FORMAT(created_at, '%Y-%m-%d') AS day,
                   COUNT(*) AS count
            FROM chat_logs
            WHERE uid=%s
              AND created_at >= NOW() - INTERVAL 7 DAY
            GROUP BY DATE_FORMAT(created_at, '%Y-%m-%d')
            ORDER BY day DESC
            """,
            (uid,),
        )
        rows = cur.fetchall()

        # 각 날짜의 가장 최근 USER 메시지
        for r in rows:
            cur.execute(
                """
                SELECT message
                FROM chat_logs
                WHERE uid=%s
                  AND speaker='user'
                  AND DATE_FORMAT(created_at, '%Y-%m-%d')=%s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (uid, r["day"]),
            )
            msg_row = cur.fetchone()
            r["last_user_msg"] = msg_row["message"] if msg_row else None

        return jsonify(ok=True, days=rows)

    except Exception as e:
        print("[ERROR] api_logs_7days:", e)
        return jsonify(ok=False, msg=str(e)), 500

    finally:
        cur.close()
        conn.close()


@app.get("/api/chat/logs/detail")
def api_logs_detail():
    if "uid" not in session:
        return jsonify(ok=False, msg="로그인 필요"), 401
    uid = session["uid"]
    date_str = (request.args.get("date") or "").strip()

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify(ok=False, msg="잘못된 날짜 형식(YYYY-MM-DD)"), 400

    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """
        SELECT speaker, message, created_at
        FROM chat_logs
        WHERE uid=%s AND DATE(created_at)=%s
        ORDER BY created_at ASC, id ASC
        """,
        (uid, date_str),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(ok=True, logs=rows, date=date_str)

## ----------------------------
# 7-B) 학교 데이터 API (수업시간표 / 학점조회 / 졸업이수)
# ----------------------------
@app.route("/api/timetable")
def api_timetable():
    student_id = request.args.get("student_id") or session.get("uid") or session.get("student_id")
    if not student_id:
        return jsonify({"ok": False, "error": "로그인이 필요합니다."})

    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)

    # URL 파라미터
    year = request.args.get("year")
    semester = request.args.get("semester")

    print(f"[DEBUG] timetable 요청: year={year}, semester={semester}, student_id={student_id}")

    try:
        if not (year and semester):
            cur.execute("""
                SELECT MAX(year) AS year, MAX(semester) AS semester
                FROM student_class
                WHERE student_id = %s
            """, (student_id,))
            info = cur.fetchone()
            if not info or not info["year"]:
                return jsonify({"ok": False, "timetable": []})
            year, semester = info["year"], info["semester"]

        # ✅ 핵심 수정: sc.schedule 사용
        cur.execute("""
            SELECT 
                c.subject,
                c.professor,
                c.classroom,
                sc.schedule,
                sc.grade
            FROM student_class sc
            JOIN class c ON sc.class_id = c.id
            WHERE sc.student_id = %s
              AND sc.year = %s
              AND sc.semester = %s
            ORDER BY sc.schedule
        """, (student_id, year, semester))

        rows = cur.fetchall() or []
        return jsonify({
            "ok": True,
            "year": year,
            "semester": semester,
            "timetable": rows
        })

    except Exception as e:
        print("[ERROR /api/timetable]", e)
        return jsonify(ok=False, msg=str(e)), 500
    finally:
        cur.close()
        conn.close()

@app.get("/api/grades")
def api_grades():
    """학생별 성적 요약 (진로지도 제외 + 학점/평균 정확히 계산)"""
    student_id = session.get("uid")
    if not student_id:
        return jsonify(ok=False, msg="로그인 필요"), 401

    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)

    try:
        # 중복 제거된 성적 목록
        cur.execute("""
            SELECT 
                c.subject,
                ANY_VALUE(c.professor) AS professor,
                ANY_VALUE(c.credit) AS credit,
                ANY_VALUE(sc.grade) AS grade,
                sc.year,
                sc.semester
            FROM student_class sc
            JOIN class c ON sc.class_id = c.id
            WHERE sc.student_id = %s
              AND c.subject NOT LIKE '%%진로지도%%'
            GROUP BY c.subject, sc.year, sc.semester
            ORDER BY sc.year DESC, sc.semester DESC
        """, (student_id,))
        rows = cur.fetchall()

        # 🔹 총 학점 (진로지도 제외)
        cur.execute("""
            SELECT SUM(c.credit) AS total_credit
            FROM (
                SELECT DISTINCT sc.class_id
                FROM student_class sc
                WHERE sc.student_id = %s
            ) AS uniq
            JOIN class c ON uniq.class_id = c.id
            WHERE c.subject NOT LIKE '%%진로지도%%';
        """, (student_id,))
        total_credit_row = cur.fetchone()
        total_credit = float(total_credit_row["total_credit"] or 0)

        grade_map = {
            "A+": 4.5, "A": 4.0, "B+": 3.5, "B": 3.0,
            "C+": 2.5, "C": 2.0, "D+": 1.5, "D": 1.0, "F": 0
        }

        total_grade_point = 0.0
        subject_count = 0

        for r in rows:
            g = r["grade"]
            if isinstance(g, str):
                g = grade_map.get(g.strip().upper(), None)
            elif isinstance(g, (float, int)):
                g = float(g)
            else:
                g = None

            if g is not None:
                credit = float(r["credit"] or 0)
                total_grade_point += g * credit
                subject_count += 1

        avg_grade = round(total_grade_point / total_credit, 2) if total_credit else 0

        return jsonify(
            ok=True,
            grades=rows,
            total_credit=total_credit,
            avg_grade=avg_grade,
            subject_count=subject_count
        )

    except Exception as e:
        print("[ERROR] /api/grades:", e)
        return jsonify(ok=False, msg=str(e)), 500
    finally:
        cur.close()
        conn.close()

@app.get("/api/grades/detail")
def api_grades_detail():
    """학기별 과목별 성적 상세 조회 (진로지도 제외 + 중복 제거)"""
    student_id = session.get("uid")
    if not student_id:
        return jsonify(ok=False, msg="로그인 필요"), 401

    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)

    try:
        # 진로지도 제외 + 중복 제거 + 학기순 정렬
        cur.execute("""
            SELECT 
                c.subject AS subject,
                ANY_VALUE(c.professor) AS professor,
                ANY_VALUE(c.credit) AS credit,
                ANY_VALUE(sc.grade) AS grade,
                sc.year,
                sc.semester
            FROM student_class sc
            JOIN class c ON sc.class_id = c.id
            WHERE sc.student_id = %s
              AND c.subject NOT LIKE '%%진로지도%%'
            GROUP BY c.subject, sc.year, sc.semester
            ORDER BY sc.year DESC, sc.semester DESC, c.subject ASC
        """, (student_id,))

        rows = cur.fetchall()

        if not rows:
            return jsonify(ok=True, details=[], msg="성적 정보가 없습니다.")

        # 문자형 등급을 숫자로 병행 표시
        grade_map = {
            "A+": 4.5, "A": 4.0, "B+": 3.5, "B": 3.0,
            "C+": 2.5, "C": 2.0, "D+": 1.5, "D": 1.0, "F": 0
        }

        for r in rows:
            g = r["grade"]
            # 등급이 문자라면 변환
            if isinstance(g, str):
                r["grade_point"] = grade_map.get(g.strip().upper(), None)
            else:
                try:
                    r["grade_point"] = float(g)
                except:
                    r["grade_point"] = None

            # credit을 float으로 통일
            try:
                r["credit"] = float(r["credit"])
            except:
                r["credit"] = 0.0

        return jsonify(ok=True, details=rows)

    except Exception as e:
        print("[ERROR] /api/grades/detail:", e)
        return jsonify(ok=False, msg=str(e)), 500
    finally:
        cur.close()
        conn.close()

@app.get("/api/graduation")
def api_graduation_status():
    """🎓 졸업요건 진행 상황 (3년제 기준: 총110 / 전공78 / 교양12)"""
    student_id = session.get("uid")
    if not student_id:
        return jsonify(ok=False, msg="로그인 필요"), 401

    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)

    try:
        # 🎯 졸업 기준
        REQ_TOTAL = 110
        REQ_MAJOR = 78
        REQ_GED = 12

        # ✅ 진로지도 제외 + 과목 중복 제거 + 전공/교양 구분
        cur.execute("""
            SELECT 
                c.course_type,
                SUM(c.credit) AS total_credit
            FROM (
                SELECT DISTINCT sc.class_id
                FROM student_class sc
                WHERE sc.student_id = CAST(%s AS CHAR)
            ) AS uniq
            JOIN class c ON uniq.class_id = c.id
            WHERE (c.subject IS NULL OR c.subject NOT LIKE '%%진로지도%%')
              AND c.course_type IS NOT NULL
            GROUP BY c.course_type
        """, (student_id,))

        rows = cur.fetchall()

        # 🎓 학점 누적
        major_required = 0
        major_elective = 0
        general_credit = 0

        for r in rows:
            ctype = str(r["course_type"]).strip()
            credit = float(r["total_credit"] or 0)

            if "전필" in ctype:
                major_required += credit
            elif "전선" in ctype:
                major_elective += credit
            elif any(key in ctype for key in ["교양", "교필", "교선"]):
                general_credit += credit

        major_credit = major_required + major_elective
        total_credit = major_credit + general_credit

        # 📊 진행률 계산
        progress_major = round((major_credit / REQ_MAJOR) * 100, 1)
        progress_general = round((general_credit / REQ_GED) * 100, 1)
        progress_total = round((total_credit / REQ_TOTAL) * 100, 1)

        # ✅ JS와 맞는 구조로 반환
        return jsonify(
            ok=True,
            graduation={
                "major_required": major_required,
                "major_elective": major_elective,
                "general": general_credit,
                "total_credit": total_credit,
                "progress": {
                    "major": progress_major,
                    "general": progress_general,
                    "total": progress_total
                }
            }
        )

    except Exception as e:
        print("[ERROR] /api/graduation:", e)
        return jsonify(ok=False, msg=str(e)), 500
    finally:
        cur.close()
        conn.close()

@app.get("/api/notices")
def api_notices():
    from pymongo import MongoClient
    import os

    client = MongoClient(os.getenv("MONGO_URI"))
    db = client["depatement_db"]
    col = db["web"]

    # 최근 10개만
    docs = list(col.find().sort("작성", -1).limit(10))
    results = []
    now = datetime.now()

    for d in docs:
        date_str = str(d.get("작성", ""))[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            dt = now
        # 최근 7일이면 NEW
        badge = "NEW" if (now - dt).days <= 7 else ""
        results.append({
            "title": d.get("title", "제목 없음"),
            "url": d.get("url", "#"),
            "date": date_str,
            "badge": badge
        })

    return jsonify(ok=True, notices=results)


# 📋 전체보기용 API
@app.get("/api/notices/all")
def api_notices_all():
    from pymongo import MongoClient
    import os

    client = MongoClient(os.getenv("MONGO_URI"))
    db = client["depatement_db"]
    col = db["web"]

    docs = list(col.find().sort("작성", -1))
    results = []
    now = datetime.now()

    for d in docs:
        date_str = str(d.get("작성", ""))[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            dt = now
        badge = "NEW" if (now - dt).days <= 7 else ""
        results.append({
            "title": d.get("title", "제목 없음"),
            "url": d.get("url", "#"),
            "date": date_str,
            "badge": badge
        })

    print("📋 전체 공지 개수:", len(results))
    return jsonify(ok=True, notices=results)

# ----------------------------
# 7-C) eClass 과제 API
# ----------------------------
@app.get("/api/subjects")
def api_subjects():
    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT DISTINCT subject_name FROM assignments ORDER BY subject_name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([r["subject_name"] for r in rows])

@app.get("/api/assignments/<subject>")
def api_assignments(subject):
    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT id, subject_name, title, due_date, status, score
        FROM assignments
        WHERE subject_name = %s
        ORDER BY due_date ASC
    """, (subject,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)

@app.get("/api/assignments/due_soon")
def api_due_soon():
    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)
    now = datetime.now()
    soon = now + timedelta(days=30)   # 🔥 기존 7일 → 30일로 확장
    cur.execute("""
        SELECT subject_name, title, due_date, status
        FROM assignments
        WHERE due_date IS NOT NULL AND due_date BETWEEN %s AND %s
        ORDER BY due_date ASC
    """, (now, soon))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)

# 모든 과제 보기
@app.get("/api/assignments/all")
def api_all_assignments():
    conn = get_raw_conn(database=DB_NAME)
    cur = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT subject_name, title, due_date, status, score
        FROM assignments
        ORDER BY due_date ASC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)

# 📘 자격증 관련 공지만 필터링
@app.get("/api/certificates")
def api_certificates():
    """MongoDB 공지 중 자격증/시험 관련 제목만 필터링"""
    from pymongo import MongoClient
    import os
    import re

    client = MongoClient(os.getenv("MONGO_URI"))
    db = client["depatement_db"]
    col = db["web"]

    # 🔍 필터링 키워드
    keywords = ["자격증", "시험", "PCCE", "인증", "Certificate"]

    # 🔍 title 필드에 위 단어 포함된 문서 검색
    query = {"$or": [{"title": {"$regex": k, "$options": "i"}} for k in keywords]}

    docs = list(col.find(query).sort("작성", -1))
    results = []
    now = datetime.now()

    for d in docs:
        date_str = str(d.get("작성", ""))[:10]
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
        except:
            dt = now
        badge = "NEW" if (now - dt).days <= 7 else ""
        results.append({
            "title": d.get("title", "제목 없음"),
            "url": d.get("url", "#"),
            "date": date_str,
            "badge": badge
        })

    print("📘 자격증 관련 공지 개수:", len(results))
    return jsonify(ok=True, certificates=results)

# =======================================
# 🏫 캠퍼스 건물 안내 API
# =======================================
@app.get("/api/campus/place")
def api_campus_place():
    """학교 위치 및 건물 안내 데이터 불러오기"""
    from pymongo import MongoClient
    import os

    try:
        client = MongoClient(os.getenv("MONGO_URI"))
        db = client["University_Introduction"]
        col = db["place"]

        # 최신순으로 모든 문서 조회
        docs = list(col.find().sort("last_updated", -1))
        results = []

        for d in docs:
            results.append({
                "title": d.get("title", "제목 없음"),
                "category": d.get("category", ""),
                "content": d.get("안내", ""),
                "manager": d.get("담당부서", ""),
                "phone": d.get("전화번호", ""),
                "keywords": d.get("키워드", []),
            })

        print(f"🏫 캠퍼스 안내 데이터 개수: {len(results)}")
        return jsonify(ok=True, places=results)
    except Exception as e:
        print("❌ 캠퍼스 안내 오류:", e)
        return jsonify(ok=False, error=str(e))
# =======================================
# 🏫 학과 정보 API
# =======================================
# =======================================
# 🏫 학과 정보 API (MONGO_URI 사용 + 경로 호환 + 로깅)
# =======================================
@app.route("/api/department/list")
@app.route("/api/departments")
def department_list():
    from pymongo import MongoClient
    import os, traceback

    try:
        # ✅ MongoDB Atlas 연결
        client = MongoClient("mongodb+srv://wjdtndpdy0920:dlwjd09tn20@cluster0.zsdkexf.mongodb.net/")
        db = client["depatement_all_db"]   # ✅ 오타 수정됨
        col = db["department"]              # ✅ 컬렉션 이름 확인

        data = []
        for d in col.find():
            # 모든 key를 문자열화 (한글 깨짐 방지)
            doc = {str(k): v for k, v in d.items()}

            # ✅ 학과명 (필수)
            name = doc.get("학과명") or doc.get("학과") or doc.get("name") or "학과명 없음"

            # ✅ 학과 소개 추출
            desc = "학과 소개 준비 중입니다."
            try:
                # sections 내부에서 "학과소개(졸업 후 진로)" → "취업분야" 같은 하위 필드 존재
                sections = doc.get("sections", {})
                if isinstance(sections, dict):
                    if "소개" in sections:
                        desc = sections["소개"]
                    elif "학과소개(졸업 후 진로)" in sections:
                        intro_obj = sections["학과소개(졸업 후 진로)"]
                        if isinstance(intro_obj, dict) and "취업분야" in intro_obj:
                            desc = f"주요 취업 분야: {', '.join(intro_obj['취업분야'])}"
                        else:
                            desc = "학과 소개 준비 중입니다."
            except:
                pass

            # ✅ 링크 처리
            link = doc.get("링크") or doc.get("url") or ""

            data.append({
                "name": name,
                "desc": desc,
                "link": link
            })

        print(f"📘 학과 문서 개수: {len(data)}")
        print("🔍 예시 데이터:", data[:3])
        return jsonify(ok=True, departments=data)

    except Exception as e:
        print("❌ /api/department/list 오류:", e)
        traceback.print_exc()
        return jsonify(ok=False, msg=str(e), departments=[]), 500

from urllib.parse import unquote

@app.route("/api/department/<name>")
def department_detail(name):
    from pymongo import MongoClient
    import traceback
    from urllib.parse import unquote

    try:
        name = unquote(name).strip()  # ✅ 한글 URL + 공백 정리
        client = MongoClient("mongodb+srv://wjdtndpdy0920:dlwjd09tn20@cluster0.zsdkexf.mongodb.net/")
        db = client["depatement_all_db"]
        col = db["department"]

        # ✅ 다양한 경우를 커버하도록 검색
        doc = col.find_one({
            "$or": [
                {"학과명": name},
                {"학과": name},
                {"name": name},
                {"sections.학과명": name},
            ]
        })

        if not doc:
            print(f"⚠️ DB에서 {name} 문서를 찾지 못했습니다.")
            return jsonify(ok=False, msg=f"{name} 학과 정보를 찾을 수 없습니다."), 404

        doc["_id"] = str(doc["_id"])
        sections = doc.get("sections", {})

        curriculum = sections.get("교육과정", {}).get("전문학사", [])
        professors = sections.get("교수소개", {})
        clubs = sections.get("전공동아리", {})
        career = sections.get("학과소개(졸업 후 진로)", {})

        result = {
            "학과명": doc.get("학과명") or doc.get("name") or name,
            "교육과정": curriculum,
            "교수소개": professors,
            "전공동아리": clubs,
            "학과소개(졸업 후 진로)": career
        }

        print(f"✅ {name} 상세정보 불러오기 성공")
        return jsonify(ok=True, department=result)

    except Exception as e:
        traceback.print_exc()
        return jsonify(ok=False, msg=str(e)), 500
# ----------------------------
#  입학 안내 PDF 분석 API
# ----------------------------
@app.get("/api/admission/info")
def api_admission_info():
    """📘 school_rules.pdf에서 주요 입학 안내 문구 추출"""
    from PyPDF2 import PdfReader
    import os

    pdf_path = "/Users/choijian/Downloads/ollama_chatbot-main/ai/data/docs/school_rules.pdf"
    if not os.path.exists(pdf_path):
        return jsonify(ok=False, msg="입학 안내 PDF를 찾을 수 없습니다."), 404

    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages[:2]:  # 🔹 앞 2페이지만 읽기
            text += page.extract_text() + "\n"

        info = {
            "모집시기": "수시 1·2차 / 정시" if "수시" in text or "정시" in text else "확인 필요",
            "지원자격": "고등학교 졸업(예정)자" if "고등학교" in text else "확인 필요",
            "전형방법": "학생부 / 면접 / 수능" if any(k in text for k in ["학생부", "면접", "수능"]) else "확인 필요"
        }

        return jsonify(ok=True, info=info)

    except Exception as e:
        return jsonify(ok=False, msg=f"PDF 분석 실패: {e}"), 500
# ✅ PDF 정적 경로 설정
@app.route("/docs/<path:filename>")
def serve_docs(filename):
    docs_dir = os.path.join(os.path.dirname(__file__), "data", "docs")
    return send_from_directory(docs_dir, filename)


# ----------------------------
# 8) HTML 페이지 라우팅
# ----------------------------
@app.get("/")
def main_page():
    return send_from_directory("templates", "main.html")

@app.get("/login.html")
def login_html():
    return send_from_directory("templates", "login.html")

@app.get("/signup.html")
def signup_page():
    return send_from_directory("templates", "signup.html")

@app.get("/guest.html")
def guest_page():
    return send_from_directory("templates", "guest.html")

@app.get("/favicon.ico")
def favicon():
    return ("", 204)

@app.get("/feature.html")
def feature_page():
    from flask import send_from_directory
    return send_from_directory("templates", "feature.html")


# ----------------------------
# 9) 서버 시작
# ----------------------------
if __name__ == "__main__":
    init_db()
    print(f"🚀 Flask 서버 실행 중: http://127.0.0.1:{PORT}")
    app.run(host="0.0.0.0", port=8001, debug=True)

