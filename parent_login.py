
import os
from datetime import datetime, timezone, timedelta, date
from types import SimpleNamespace

import razorpay
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from itsdangerous import URLSafeTimedSerializer
from pymongo import ReturnDocument
from werkzeug.security import check_password_hash

from db import (
    master_col, counters_collection,
    tran_collection as tran_col,
    get_school, attendance_collection
)
from parent_homework import homework_bp

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

IST = timezone(timedelta(hours=5, minutes=30))
MONTHS = "April May June July August September October November December January February March".split()
LATE_FEE_PER_DAY = 5
DUE_DAY = 10

HEADS = [
    "admission_fee", "annual_fee", "tuition_fee", "transport_fee",
    "devl_fee", "eclass", "science", "computer", "kgarten"
]

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "change-this-secret-key")
app.register_blueprint(homework_bp)

KEY = os.environ.get("RAZORPAY_KEY_ID", "").strip()
SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
rz = razorpay.Client(auth=(KEY, SECRET)) if KEY and SECRET else None


def money(x):
    try:
        return round(float(x or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def school():
    s = get_school() or {}
    return {
        "name": s.get("school_name", ""),
        "address": s.get("address", ""),
        "phone": s.get("phone", ""),
        "logo": s.get("logo", "")
    }


def receipt():
    c = counters_collection.find_one_and_update(
        {"_id": "receipt_number"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return f"REC-{c['seq']:05d}"


def fee(s, m):
    total = money(s.get("tuition_fee"))

    for k in ("devl_fee", "eclass", "science", "computer", "kgarten"):
        total += money(s.get(k)) / 12

    transport = money(s.get("transport_total")) / \
        10.5 if s.get("transport_total") else 0
    total += transport / 2 if m == "May" else 0 if m == "June" else transport

    if m == "April":
        total += money(s.get("admission_fee")) + money(s.get("annual_fee"))

    return round(total, 2)


def monthly_heads(s, m):
    transport = money(s.get("transport_total")) / \
        10.5 if s.get("transport_total") else 0

    return {
        "admission_fee": money(s.get("admission_fee")) if m == "April" else 0,
        "annual_fee": money(s.get("annual_fee")) if m == "April" else 0,
        "tuition_fee": money(s.get("tuition_fee")),
        "transport_fee": round(
            transport / 2 if m == "May" else 0 if m == "June" else transport, 2
        ),
        "devl_fee": round(money(s.get("devl_fee")) / 12, 2),
        "eclass": round(money(s.get("eclass")) / 12, 2),
        "science": round(money(s.get("science")) / 12, 2),
        "computer": round(money(s.get("computer")) / 12, 2),
        "kgarten": round(money(s.get("kgarten")) / 12, 2)
    }


def tx_months(t):
    md = t.get("month_details")
    if isinstance(md, dict) and md:
        return list(md)

    m = t.get("month") or t.get("selected_month") or t.get(
        "selected_months") or t.get("months")
    return m if isinstance(m, list) else [m] if m else []


def tx_paid(t, m=None):
    md = t.get("month_details")

    if m and isinstance(md, dict) and m in md:
        d = md[m] or {}
        return money(d.get("paid", d.get("fee_paid", d.get("paid_amount", d.get("amount_paid", 0)))))

    if "fee_paid" in t:
        return money(t.get("fee_paid"))

    return money(t.get("paid_amount", t.get("paid", t.get("amount_paid", 0))))


def month_paid(adm, m):
    return round(sum(
        tx_paid(t, m)
        for t in tran_col.find({"adm_code": adm})
        if m in tx_months(t)
    ), 2)


def month_head_paid(adm, m):
    student = master_col.find_one({"adm_code": adm}) or {}
    paid = {k: 0.0 for k in HEADS}

    for t in tran_col.find({"adm_code": adm}):
        md = t.get("month_details") or {}
        detail = md.get(m, {}) if isinstance(md, dict) else {}
        heads = detail.get("heads", {}) if isinstance(detail, dict) else {}

        if heads:
            for k in HEADS:
                paid[k] += money((heads.get(k) or {}).get("paid", 0))

    legacy = max(month_paid(adm, m) - sum(paid.values()), 0)
    totals = monthly_heads(student, m)

    for k in HEADS:
        allocation = min(legacy, max(totals[k] - paid[k], 0))
        paid[k] += allocation
        legacy -= allocation

    return {k: round(v, 2) for k, v in paid.items()}


def month_balance(adm, m):
    result = None

    for t in tran_col.find({"adm_code": adm}).sort("date", 1):
        md = t.get("month_details")

        if isinstance(md, dict) and m in md:
            d = md[m] or {}
            if isinstance(d, dict) and "balance" in d:
                result = money(d["balance"])
        elif m in tx_months(t):
            if "balance_amount" in t:
                result = money(t["balance_amount"])
            elif "balance" in t:
                result = money(t["balance"])

    return result


def balance(s, adm, m):
    b = month_balance(adm, m)
    return max(b, 0) if b is not None else round(max(fee(s, m) - month_paid(adm, m), 0), 2)


def month_late_fee_paid(adm, m):
    total = 0

    for t in tran_col.find({"adm_code": adm}):
        d = (t.get("month_details") or {}).get(m, {})

        if isinstance(d, dict):
            total += money(d.get("late_fee_paid", 0))
        elif m in tx_months(t):
            total += money(t.get("late_fee_paid", t.get("late_fee", 0)))

    return round(total, 2)


def month_late_fee_assessed(adm, m):
    assessed = 0

    for t in tran_col.find({"adm_code": adm}):
        d = (t.get("month_details") or {}).get(m, {})

        if isinstance(d, dict):
            assessed = max(assessed, money(
                d.get("late_fee_assessed", d.get("late_fee", 0))))

    return assessed


def month_late_fee(s, adm, m, today=None):
    today = today or datetime.now(IST).date()
    base_balance = balance(s, adm, m)
    assessed = month_late_fee_assessed(adm, m)

    year = today.year if today.month >= 4 else today.year - 1
    month_number = MONTHS.index(m) + 4
    if month_number > 12:
        month_number -= 12

    due = date(year if MONTHS.index(m) <
               9 else year + 1, month_number, DUE_DAY)

    if base_balance > 0 and today > due:
        assessed = max(assessed, (today - due).days * LATE_FEE_PER_DAY)

    return round(max(assessed - month_late_fee_paid(adm, m), 0), 2)


def paid_status(s, adm, m):
    return balance(s, adm, m) <= 0 and month_late_fee(s, adm, m) <= 0


def first_due_month(s, adm):
    return next((m for m in MONTHS if not paid_status(s, adm, m)), "April")


def payable(s, adm, m):
    i = MONTHS.index(m)
    return round(sum(
        balance(s, adm, x) + month_late_fee(s, adm, x)
        for x in MONTHS[:i + 1]
    ), 2)


def outstanding(s, adm):
    return round(sum(
        balance(s, adm, m) + month_late_fee(s, adm, m)
        for m in MONTHS
    ), 2)


def history(adm):
    rows = []

    for x in tran_col.find({"adm_code": adm}).sort("date", -1):
        x["month"] = ", ".join(tx_months(x))
        rows.append(SimpleNamespace(**x))

    return rows


# ---------------- PARENT LOGIN API ----------------

@app.route("/api/login", methods=["POST"])
def api_login():
    try:
        d = request.get_json() or {}
        adm = str(d.get("adm_code", "")).strip().upper()
        pwd = str(d.get("password", "")).strip()

        if not adm or not pwd:
            return jsonify(success=False, message="Admission Code and Password required"), 400

        s = master_col.find_one({"adm_code": adm})

        if not s:
            return jsonify(success=False, message="Invalid Admission Code"), 401

        if not s.get("password_hash") or not check_password_hash(s["password_hash"], pwd):
            return jsonify(success=False, message="Incorrect Password"), 401

        token = URLSafeTimedSerializer(
            app.secret_key,
            salt="parent-homework"
        ).dumps({"adm_code": adm})

        sc = school()

        return jsonify({
            "success": True,
            "token": token,
            "adm_code": adm,
            "student_name": s.get("student_name", ""),
            "class": s.get("class", ""),
            "section": s.get("sec", s.get("section", "")),
            "father_name": s.get("father_name", ""),
            "photo": s.get("photo", ""),
            "school_name": sc.get("name", ""),
            "school_address": sc.get("address", ""),
            "school_phone": sc.get("phone", "")
        }), 200

    except Exception:
        app.logger.exception("Parent API login failed")
        return jsonify(success=False, message="Unable to process login"), 500


# ---------------- WEB LOGIN ----------------

@app.route("/", methods=["GET", "POST"])
def login():
    adm = request.args.get("adm_code", "").strip().upper()

    if adm and master_col.find_one({"adm_code": adm}):
        session["admission_code"] = adm
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        adm = request.form.get("adm_code", "").strip().upper()
        pwd = request.form.get("password", "")
        s = master_col.find_one({"adm_code": adm})

        if s and s.get("password_hash") and check_password_hash(s["password_hash"], pwd):
            session["admission_code"] = adm
            return redirect(url_for("dashboard"))

        flash("Invalid login credentials", "error")

    return render_template("parent_login.html", school=school())


# ---------------- DASHBOARD ----------------

@app.route("/dashboard")
def dashboard():
    if "admission_code" not in session:
        return redirect(url_for("login"))

    adm = session["admission_code"]
    s = master_col.find_one({"adm_code": adm})

    if not s:
        flash("Student record not found", "error")
        return redirect(url_for("login"))

    attendance = list(attendance_collection.find({"adm_code": adm}))
    present = sum(x.get("status") == "Present" for x in attendance)
    absent = sum(x.get("status") == "Absent" for x in attendance)
    leave = sum(x.get("status") == "Leave" for x in attendance)

    at = present + absent + leave
    ap = round(present * 100 / at, 1) if at else 0

    requested = request.args.get("month")
    selected = requested if requested in MONTHS and not paid_status(
        s, adm, requested) else first_due_month(s, adm)

    current_fee = fee(s, selected)
    current_paid = month_paid(adm, selected)
    current_balance = balance(s, adm, selected)
    current_late_fee = month_late_fee(s, adm, selected)
    current_total_due = round(current_balance + current_late_fee, 2)

    i = MONTHS.index(selected)
    previous_balance = round(sum(
        balance(s, adm, m) + month_late_fee(s, adm, m)
        for m in MONTHS[:i]
    ), 2)

    student_balance = outstanding(s, adm)
    late_fees = {m: month_late_fee(s, adm, m) for m in MONTHS}

    return render_template(
        "parent_dashboard.html",
        student=SimpleNamespace(**s),
        total=round(previous_balance + current_total_due, 2),
        current_fee=current_fee,
        current_paid=current_paid,
        current_balance=current_balance,
        current_late_fee=current_late_fee,
        current_total_due=current_total_due,
        previous_balance=previous_balance,
        balance=student_balance,
        outstanding=student_balance,
        auto_paid=current_paid,
        history=history(adm),
        paid_months=[m for m in MONTHS if paid_status(s, adm, m)],
        month_balances={m: balance(s, adm, m) for m in MONTHS},
        month_late_fees=late_fees,
        months=MONTHS,
        selected_month=selected,
        razorpay_key_id=KEY,
        photo=s.get("photo", ""),
        school=school(),
        present=present,
        absent=absent,
        leave=leave,
        attendance_total=at,
        attendance_percent=ap,
        late_fee_per_day=LATE_FEE_PER_DAY,
        late_fee_due_day=DUE_DAY
    )


# ---------------- RAZORPAY ORDER ----------------

@app.route("/create_order", methods=["POST"])
def create_order():
    if not rz:
        return jsonify(error="Razorpay keys are not configured."), 503

    adm = request.form.get("admission_code", "").strip().upper()
    m = request.form.get("month") or request.form.get("selected_month") or ""
    s = master_col.find_one({"adm_code": adm})

    if not s:
        return jsonify(error="Student not found"), 404

    if m and m not in MONTHS:
        return jsonify(error="Invalid month"), 400

    amount = money(request.form.get("paid"))

    if m:
        max_amount = payable(s, adm, m)
        if amount <= 0 or amount > max_amount + 0.01:
            return jsonify(error=f"Maximum payable amount including late fee is ₹{max_amount:.2f}"), 400
    elif amount <= 0:
        return jsonify(error="Invalid amount"), 400

    try:
        order = rz.order.create({
            "amount": int(round(amount * 100)),
            "currency": "INR",
            "payment_capture": "1"
        })

        return jsonify(
            order_id=order["id"],
            admission_code=adm,
            amount=int(round(amount * 100))
        )
    except Exception as e:
        app.logger.exception("Razorpay order creation failed")
        return jsonify(error=str(e)), 500


# ---------------- RAZORPAY PAYMENT VERIFY ----------------

@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    try:
        if not rz:
            return jsonify(status="error", message="Razorpay keys are not configured."), 503

        d = request.get_json() or {}

        rz.utility.verify_payment_signature({
            "razorpay_order_id": d["order_id"],
            "razorpay_payment_id": d["payment_id"],
            "razorpay_signature": d["signature"]
        })

        payment = rz.payment.fetch(d["payment_id"])

        if payment.get("status") != "captured":
            return jsonify(status="failed")

        adm = str(d.get("admission_code", "")).strip().upper()
        month_selected = d.get("month")
        student = master_col.find_one({"adm_code": adm})

        if not student:
            return jsonify(status="error", message="Student not found"), 404

        if month_selected not in MONTHS:
            return jsonify(status="error", message="Invalid month"), 400

        collected_total = money(d.get("paid"))

        if int(round(collected_total * 100)) != int(payment.get("amount", 0)):
            return jsonify(status="error", message="Payment amount mismatch"), 400

        max_payable = payable(student, adm, month_selected)

        if collected_total <= 0 or collected_total > max_payable + 0.01:
            return jsonify(
                status="error",
                message=f"Maximum payable amount including late fee is ₹{max_payable:.2f}"
            ), 400

        remaining = collected_total
        details = {}
        receipt_head_totals = {k: 0.0 for k in HEADS}

        for month in MONTHS[:MONTHS.index(month_selected) + 1]:
            base_due = balance(student, adm, month)
            fine_due = month_late_fee(student, adm, month)

            if base_due <= 0 and fine_due <= 0:
                continue

            fee_paid = round(min(remaining, base_due), 2)
            remaining = round(remaining - fee_paid, 2)

            month_heads_data = monthly_heads(student, month)
            previous_heads_paid = month_head_paid(adm, month)
            head_details = {}

            for key in HEADS:
                head_total = money(month_heads_data.get(key, 0))
                already_paid = money(previous_heads_paid.get(key, 0))
                head_balance = max(head_total - already_paid, 0)

                head_details[key] = {
                    "total": head_total,
                    "paid_before": already_paid,
                    "paid": 0.0,
                    "balance": head_balance
                }

            head_remaining = fee_paid

            for key in HEADS:
                head_balance = head_details[key]["balance"]
                head_paid_now = round(min(head_remaining, head_balance), 2)

                head_details[key]["paid"] = head_paid_now
                head_details[key]["balance"] = round(
                    head_balance - head_paid_now, 2)

                receipt_head_totals[key] += head_paid_now
                head_remaining = round(head_remaining - head_paid_now, 2)

            fine_paid = round(min(remaining, fine_due), 2)
            remaining = round(remaining - fine_paid, 2)

            fine_already_paid = month_late_fee_paid(adm, month)
            fine_assessed_before = month_late_fee_assessed(adm, month)
            fine_assessed_total = round(
                max(fine_assessed_before, fine_already_paid + fine_due), 2)

            details[month] = {
                "total": fee(student, month),
                "already_paid": round(fee(student, month) - base_due, 2),
                "paid": fee_paid,
                "balance": round(base_due - fee_paid, 2),
                "heads": head_details,
                "late_fee_assessed": fine_assessed_total,
                "late_fee_paid": fine_paid,
                "late_fee": fine_due,
                "late_fee_balance": round(fine_due - fine_paid, 2)
            }

            if remaining <= 0:
                break

        if remaining > 0.01:
            return jsonify(status="error", message="Unable to allocate full payment"), 400

        if not details:
            return jsonify(status="error", message="No outstanding fee found"), 400

        receipt_no = receipt()
        fee_paid_total = round(sum(x["paid"] for x in details.values()), 2)
        fine_paid_total = round(sum(x["late_fee_paid"]
                                for x in details.values()), 2)

        old_balance = money(student.get(
            "balance_fee", student.get("total_fee", 0)))
        new_balance = max(old_balance - fee_paid_total, 0)

        fee_balance_after = round(sum(x["balance"]
                                  for x in details.values()), 2)
        fine_balance_after = round(
            sum(x["late_fee_balance"] for x in details.values()), 2)

        transaction = {
            "receipt_no": receipt_no,
            "adm_code": adm,
            "student_name": student.get("student_name", ""),
            "class": student.get("class", ""),
            "section": student.get("sec", student.get("section", "")),
            "father_name": student.get("father_name", ""),
            "photo": student.get("photo", ""),
            "months": list(details),
            "month": month_selected,
            "selected_month": month_selected,
            "month_details": details,
            "head_totals": {k: round(v, 2) for k, v in receipt_head_totals.items()},
            "paid_head_totals": {k: round(v, 2) for k, v in receipt_head_totals.items()},
            "month_total": round(sum(x["total"] for x in details.values()), 2),
            "amount_paid": fee_paid_total,
            "paid_amount": fee_paid_total,
            "paid": fee_paid_total,
            "fee_paid": fee_paid_total,
            "balance_amount": fee_balance_after,
            "balance": fee_balance_after,
            "student_balance": new_balance,
            "late_fee": fine_paid_total,
            "late_fee_paid": fine_paid_total,
            "auto_late_fee": fine_paid_total,
            "late_fee_balance": fine_balance_after,
            "total_collected": collected_total,
            "payment_total": collected_total,
            "is_balance_payment": True,
            "payment_type": "Online Payment",
            "payment_id": d["payment_id"],
            "order_id": d["order_id"],
            "payment_mode": "Online",
            "remark": d.get("remarks", ""),
            "date": datetime.now(IST).replace(tzinfo=None)
        }

        tran_col.insert_one(transaction)

        master_col.update_one(
            {"adm_code": adm},
            {
                "$inc": {"paid_fee": fee_paid_total},
                "$set": {"balance_fee": new_balance}
            }
        )

        return jsonify(
            status="success",
            receipt_no=receipt_no,
            paid=fee_paid_total,
            fee_paid=fee_paid_total,
            late_fee_paid=fine_paid_total,
            total_collected=collected_total,
            balance=fee_balance_after,
            months=list(details)
        )

    except Exception as e:
        app.logger.exception("Payment verification failed")
        return jsonify(status="error", message=str(e)), 400


# ---------------- LOGOUT ----------------

@app.route("/logout")
def logout():
    session.pop("admission_code", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
