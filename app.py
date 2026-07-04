from __future__ import annotations

import calendar as _calendar
import os
from datetime import datetime, date, timedelta
from typing import Optional
from flask import Flask, render_template, redirect, url_for, request, flash, abort
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
)
from sqlalchemy import and_, or_

from models import db, Admin, Room, Reservation, RESERVATION_STATUS


DEFAULT_ROOMS = [
    {"name": "101호", "description": "1층 스탠다드 룸", "capacity": 2},
    {"name": "201호", "description": "2층 스탠다드 룸", "capacity": 2},
    {"name": "202호", "description": "2층 디럭스 룸", "capacity": 4},
]


def _normalize_db_url(url: str) -> str:
    # Neon / Heroku 스타일 postgres:// -> SQLAlchemy 표준으로 정규화
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _bootstrap(app: Flask) -> None:
    """서버리스 환경에서 첫 요청 시 테이블/시드/관리자 계정을 자동 생성."""
    with app.app_context():
        db.create_all()
        for data in DEFAULT_ROOMS:
            if not Room.query.filter_by(name=data["name"]).first():
                db.session.add(Room(**data))
        if not Admin.query.first():
            username = os.environ.get("ADMIN_USER", "admin")
            password = os.environ.get("ADMIN_PASS", "admin1234")
            admin = Admin(username=username)
            admin.set_password(password)
            db.session.add(admin)
        db.session.commit()


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = _normalize_db_url(
        os.environ.get("DATABASE_URL", "sqlite:///reserve.db")
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    db.init_app(app)
    _bootstrap(app)

    login_manager = LoginManager(app)
    login_manager.login_view = "login"

    @login_manager.user_loader
    def load_user(user_id: str):
        return db.session.get(Admin, int(user_id))

    @app.route("/")
    def index():
        today = date.today()
        year = request.args.get("year", type=int) or today.year
        month = request.args.get("month", type=int) or today.month
        if not 1 <= month <= 12:
            month = today.month

        rooms = Room.query.order_by(Room.name).all()
        weeks = _build_month_grid(year, month)
        availability = _availability_map(year, month, rooms)

        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

        return render_template(
            "calendar.html",
            rooms=rooms,
            weeks=weeks,
            availability=availability,
            year=year,
            month=month,
            today=today,
            prev_year=prev_year,
            prev_month=prev_month,
            next_year=next_year,
            next_month=next_month,
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("reservations"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            admin = Admin.query.filter_by(username=username).first()
            if admin and admin.check_password(password):
                login_user(admin)
                return redirect(url_for("reservations"))
            flash("아이디 또는 비밀번호가 올바르지 않습니다.", "error")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("index"))

    @app.route("/reservations")
    @login_required
    def reservations():
        room_id = request.args.get("room_id", type=int)
        status = request.args.get("status")
        query = Reservation.query.order_by(Reservation.check_in_date.desc())
        if room_id:
            query = query.filter_by(room_id=room_id)
        if status in RESERVATION_STATUS:
            query = query.filter_by(status=status)
        items = query.all()
        rooms = Room.query.order_by(Room.name).all()
        return render_template(
            "reservations.html",
            reservations=items,
            rooms=rooms,
            selected_room_id=room_id,
            selected_status=status,
        )

    @app.route("/reservations/new", methods=["GET", "POST"])
    @login_required
    def reservation_new():
        rooms = Room.query.order_by(Room.name).all()
        if request.method == "POST":
            next_url = _safe_next(request.form.get("next"))
            try:
                res = _reservation_from_form(request.form)
            except ValueError as e:
                flash(str(e), "error")
                return render_template(
                    "reservation_form.html", rooms=rooms, reservation=None
                )
            conflict = _find_conflict(res.room_id, res.check_in_date, res.check_out_date)
            if conflict:
                flash(
                    f"해당 기간에 이미 예약이 존재합니다 (#{conflict.id} {conflict.guest_name}).",
                    "error",
                )
                return render_template(
                    "reservation_form.html", rooms=rooms, reservation=None
                )
            db.session.add(res)
            db.session.commit()
            flash("예약이 등록되었습니다.", "success")
            return redirect(next_url or url_for("reservations"))
        return render_template("reservation_form.html", rooms=rooms, reservation=None)

    @app.route("/reservations/calendar")
    @login_required
    def reservations_calendar():
        today = date.today()
        year = request.args.get("year", type=int) or today.year
        month = request.args.get("month", type=int) or today.month
        if not 1 <= month <= 12:
            month = today.month

        rooms = Room.query.order_by(Room.name).all()
        weeks = _build_month_grid(year, month)
        availability = _availability_map(year, month, rooms)
        reservations_by_date = _reservations_by_date(year, month, rooms)

        prev_year, prev_month = (year - 1, 12) if month == 1 else (year, month - 1)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)

        rooms_json = [
            {"id": r.id, "name": r.name, "capacity": r.capacity} for r in rooms
        ]

        return render_template(
            "reservations_calendar.html",
            rooms=rooms,
            rooms_json=rooms_json,
            weeks=weeks,
            availability=availability,
            reservations_by_date=reservations_by_date,
            year=year,
            month=month,
            today=today,
            prev_year=prev_year,
            prev_month=prev_month,
            next_year=next_year,
            next_month=next_month,
        )

    @app.route("/reservations/<int:res_id>/edit", methods=["GET", "POST"])
    @login_required
    def reservation_edit(res_id: int):
        res = db.session.get(Reservation, res_id) or abort(404)
        rooms = Room.query.order_by(Room.name).all()
        if request.method == "POST":
            try:
                _apply_form(res, request.form)
            except ValueError as e:
                flash(str(e), "error")
                return render_template(
                    "reservation_form.html", rooms=rooms, reservation=res
                )
            conflict = _find_conflict(
                res.room_id, res.check_in_date, res.check_out_date, exclude_id=res.id
            )
            if conflict and res.status == "CONFIRMED":
                flash(
                    f"해당 기간에 이미 예약이 존재합니다 (#{conflict.id} {conflict.guest_name}).",
                    "error",
                )
                return render_template(
                    "reservation_form.html", rooms=rooms, reservation=res
                )
            db.session.commit()
            flash("예약이 수정되었습니다.", "success")
            return redirect(url_for("reservations"))
        return render_template("reservation_form.html", rooms=rooms, reservation=res)

    @app.route("/reservations/<int:res_id>/cancel", methods=["POST"])
    @login_required
    def reservation_cancel(res_id: int):
        res = db.session.get(Reservation, res_id) or abort(404)
        res.status = "CANCELED"
        db.session.commit()
        flash("예약이 취소되었습니다.", "success")
        return redirect(url_for("reservations"))

    @app.route("/reservations/<int:res_id>/delete", methods=["POST"])
    @login_required
    def reservation_delete(res_id: int):
        res = db.session.get(Reservation, res_id) or abort(404)
        db.session.delete(res)
        db.session.commit()
        flash("예약이 삭제되었습니다.", "success")
        return redirect(url_for("reservations"))

    @app.route("/rooms")
    @login_required
    def rooms():
        items = Room.query.order_by(Room.name).all()
        return render_template("rooms.html", rooms=items)

    return app


def _reservation_from_form(form) -> Reservation:
    room_id = int(form.get("room_id"))
    guest_name = form.get("guest_name", "").strip()
    phone = form.get("phone", "").strip()
    memo = form.get("memo", "").strip()
    status = form.get("status", "CONFIRMED")
    check_in = _parse_date(form.get("check_in_date"))
    check_out = _parse_date(form.get("check_out_date"))
    _validate(guest_name, phone, check_in, check_out, status, room_id)
    return Reservation(
        room_id=room_id,
        guest_name=guest_name,
        phone=phone,
        memo=memo,
        check_in_date=check_in,
        check_out_date=check_out,
        status=status,
    )


def _apply_form(res: Reservation, form) -> None:
    room_id = int(form.get("room_id"))
    guest_name = form.get("guest_name", "").strip()
    phone = form.get("phone", "").strip()
    memo = form.get("memo", "").strip()
    status = form.get("status", "CONFIRMED")
    check_in = _parse_date(form.get("check_in_date"))
    check_out = _parse_date(form.get("check_out_date"))
    _validate(guest_name, phone, check_in, check_out, status, room_id)
    res.room_id = room_id
    res.guest_name = guest_name
    res.phone = phone
    res.memo = memo
    res.check_in_date = check_in
    res.check_out_date = check_out
    res.status = status


def _parse_date(value: str | None) -> date:
    if not value:
        raise ValueError("날짜를 입력해 주세요.")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("날짜 형식이 올바르지 않습니다 (YYYY-MM-DD).") from exc


def _validate(
    guest_name: str,
    phone: str,
    check_in: date,
    check_out: date,
    status: str,
    room_id: int,
) -> None:
    if not guest_name:
        raise ValueError("게스트 이름을 입력해 주세요.")
    if not phone:
        raise ValueError("연락처를 입력해 주세요.")
    if check_out <= check_in:
        raise ValueError("체크아웃 날짜는 체크인 날짜 이후여야 합니다.")
    if status not in RESERVATION_STATUS:
        raise ValueError("잘못된 상태 값입니다.")
    if not db.session.get(Room, room_id):
        raise ValueError("존재하지 않는 객실입니다.")


def _build_month_grid(year: int, month: int) -> list[list[date]]:
    """월 달력을 주 단위 리스트로 반환 (일요일 시작). 인접 달 날짜 포함."""
    cal = _calendar.Calendar(firstweekday=6)  # 일요일 시작
    return [
        [d for d in week] for week in cal.monthdatescalendar(year, month)
    ]


def _availability_map(
    year: int, month: int, rooms: list[Room]
) -> dict[tuple[int, int, int, int], bool]:
    """(room_id, y, m, d) -> booked 여부. 조회 대상은 표시되는 6주 범위."""
    weeks = _build_month_grid(year, month)
    if not weeks:
        return {}
    start = weeks[0][0]
    end = weeks[-1][-1] + timedelta(days=1)

    room_ids = [r.id for r in rooms]
    reservations = Reservation.query.filter(
        Reservation.status == "CONFIRMED",
        Reservation.room_id.in_(room_ids),
        Reservation.check_in_date < end,
        Reservation.check_out_date > start,
    ).all()

    result: dict[tuple[int, int, int, int], bool] = {}
    for r in reservations:
        d = r.check_in_date
        while d < r.check_out_date:
            if start <= d < end:
                result[(r.room_id, d.year, d.month, d.day)] = True
            d += timedelta(days=1)
    return result


def _reservations_by_date(
    year: int, month: int, rooms: list[Room]
) -> dict[str, list[dict]]:
    """표시되는 6주 범위 내에서 날짜별 예약 목록. key는 'YYYY-MM-DD'."""
    weeks = _build_month_grid(year, month)
    if not weeks:
        return {}
    start = weeks[0][0]
    end = weeks[-1][-1] + timedelta(days=1)

    room_ids = [r.id for r in rooms]
    room_names = {r.id: r.name for r in rooms}
    reservations = Reservation.query.filter(
        Reservation.room_id.in_(room_ids),
        Reservation.check_in_date < end,
        Reservation.check_out_date > start,
    ).all()

    result: dict[str, list[dict]] = {}
    for r in reservations:
        item = {
            "id": r.id,
            "room_id": r.room_id,
            "room_name": room_names.get(r.room_id, ""),
            "guest_name": r.guest_name,
            "phone": r.phone,
            "status": r.status,
            "memo": r.memo,
            "check_in": r.check_in_date.isoformat(),
            "check_out": r.check_out_date.isoformat(),
        }
        d = r.check_in_date
        while d < r.check_out_date:
            if start <= d < end:
                result.setdefault(d.isoformat(), []).append(item)
            d += timedelta(days=1)
    return result


def _safe_next(candidate: Optional[str]) -> Optional[str]:
    """오픈 리다이렉트 방지 — 로컬 경로만 허용."""
    if not candidate:
        return None
    if candidate.startswith("/") and not candidate.startswith("//"):
        return candidate
    return None


def _find_conflict(
    room_id: int, check_in: date, check_out: date, exclude_id: int | None = None
) -> Reservation | None:
    query = Reservation.query.filter(
        Reservation.room_id == room_id,
        Reservation.status == "CONFIRMED",
        and_(
            Reservation.check_in_date < check_out,
            Reservation.check_out_date > check_in,
        ),
    )
    if exclude_id is not None:
        query = query.filter(Reservation.id != exclude_id)
    return query.first()


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
