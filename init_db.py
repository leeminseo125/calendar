import os
import sys
from app import app
from models import db, Admin, Room


ROOMS = [
    {"name": "101호", "description": "1층 스탠다드 룸", "capacity": 2},
    {"name": "201호", "description": "2층 스탠다드 룸", "capacity": 2},
    {"name": "202호", "description": "2층 디럭스 룸", "capacity": 4},
]


def init(username: str, password: str) -> None:
    with app.app_context():
        db.create_all()

        for data in ROOMS:
            if not Room.query.filter_by(name=data["name"]).first():
                db.session.add(Room(**data))

        if not Admin.query.filter_by(username=username).first():
            admin = Admin(username=username)
            admin.set_password(password)
            db.session.add(admin)

        db.session.commit()
        print(f"초기화 완료. 관리자 계정: {username}")


if __name__ == "__main__":
    user = os.environ.get("ADMIN_USER", "admin")
    pw = os.environ.get("ADMIN_PASS", "admin1234")
    if len(sys.argv) >= 3:
        user, pw = sys.argv[1], sys.argv[2]
    init(user, pw)
