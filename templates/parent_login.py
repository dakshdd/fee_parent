from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import check_password_hash
from pymongo import MongoClient, ReturnDocument
from types import SimpleNamespace
import razorpay
import os
import datetime
from db import master_collection, counters_collection, tran_collection as tran_col, master_col
from datetime import timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "default_secret")


RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_SDy9xMyjmCtIEt")
RAZORPAY_KEY_SECRET = os.environ.get(
    "RAZORPAY_KEY_SECRET", "75xgs943MeNtbDqy4PH1p3Fh")
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))


def get_next_receipt_number():
    c = counters_collection.find_one_and_update(
        {"_id": "receipt_number"},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER
    )
    return f"REC-{c['seq']:05d}"


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        adm_code = request.form.get("adm_code", "").strip()
        password = request.form.get("password", "")
        r = master_col.find_one({"adm_code": adm_code})
        if r and "password_hash" in r and check_password_hash(r["password_hash"], password):
            session["admission_code"] = adm_code
            return redirect(url_for("dashboard"))
        flash("Invalid login credentials", "error")
    return render_template("parent_login.html")


@app.route("/dashboard")
def dashboard():
    if "admission_code" not in session:
        return redirect(url_for("login"))

    adm_code = session["admission_code"]
    r = master_col.find_one({"adm_code": adm_code})
    if not r:
        flash("Student record not found", "error")
        return redirect(url_for("login"))

    admission = r.get("admission_fee", 0)
    annual = r.get("annual_fee", 0)
    tuition = r.get("tuition_fee", 0)
    devl = r.get("devl_fee", 0)/12
    eclass = r.get("eclass", 0)/12
    science = r.get("science", 0)/12
    computer = r.get("computer", 0)/12
    kgarten = r.get("kgarten", 0)/12
    transport = r.get("transport_total", 0)/12

    history = [SimpleNamespace(
        **x) for x in tran_col.find({"adm_code": adm_code}).sort("date", -1)]
    paid_months = [x.month for x in history if hasattr(x, "month")]

    months = ["April", "May", "June", "July", "August", "September",
              "October", "November", "December", "January", "February", "March"]
    selected_month = request.args.get("month")

    if not selected_month:
        selected_month = next(
            (m for m in months if m not in paid_months), None)

    if not selected_month:
        selected_month = datetime.datetime.now().strftime("%B")

    if selected_month == "April":
        total = admission+annual+tuition+devl+eclass+science+computer+kgarten+transport
    else:
        total = tuition+devl+eclass+science+computer+kgarten+transport

    return render_template(
        "parent_dashboard.html",
        student=SimpleNamespace(**r),
        total=total,
        balance=r.get("balance_fee", total),
        auto_paid=total,
        history=history,
        paid_months=paid_months,
        razorpay_key_id=RAZORPAY_KEY_ID,
        selected_month=selected_month,
        photo=r.get("photo", "")
    )


@app.route("/create_order", methods=["POST"])
def create_order():
    amount = int(float(request.form.get("paid", 0))*100)
    order = razorpay_client.order.create({
        "amount": amount,
        "currency": "INR",
        "payment_capture": "1"
    })
    return jsonify({
        "order_id": order["id"],
        "admission_code": request.form.get("admission_code")
    })


@app.route("/verify_payment", methods=["POST"])
def verify_payment():
    data = request.get_json()

    try:
        razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": data["order_id"],
            "razorpay_payment_id": data["payment_id"],
            "razorpay_signature": data["signature"]
        })

        payment = razorpay_client.payment.fetch(data["payment_id"])
        if payment["status"] != "captured":
            return {"status": "failed"}

        adm_code = data["admission_code"]
        month = data.get("month")

        if tran_col.find_one({"adm_code": adm_code, "month": month}):
            return {"status": "error", "message": "Fee for this month already paid"}

        r = master_col.find_one({"adm_code": adm_code})
        if not r:
            return {"status": "error", "message": "Student not found"}

        admission = r.get("admission_fee", 0)
        annual = r.get("annual_fee", 0)
        tuition = r.get("tuition_fee", 0)
        devl = r.get("devl_fee", 0)/12
        eclass = r.get("eclass", 0)/12
        science = r.get("science", 0)/12
        computer = r.get("computer", 0)/12
        kgarten = r.get("kgarten", 0)/12
        transport = r.get("transport_total", 0)/12

        if month == "April":
            expected = admission+annual+tuition+devl + \
                eclass+science+computer+kgarten+transport
        else:
            expected = tuition+devl+eclass+science+computer+kgarten+transport

        paid = float(data.get("paid", 0))

        if abs(paid-expected) > 1:
            return {
                "status": "error",
                "message": f"Invalid amount. Expected {expected}, got {paid}"
            }

        prev_balance = float(r.get("balance_fee", r.get("total_fee", 0)))
        new_balance = max(prev_balance-paid, 0)
        receipt_no = get_next_receipt_number()

        tran_col.insert_one({
            "receipt_no": receipt_no,
            "adm_code": adm_code,
            "student_name": data["student_name"],
            "class": data["class"],
            "father_name": data["father_name"],
            "photo": data["photo"],
            "admission_fee": admission if month == "April" else 0,
            "annual_fee": annual if month == "April" else 0,
            "tuition_fee": tuition,
            "transport_fee": transport,
            "devl_fee": devl,
            "eclass": eclass,
            "science": science,
            "computer": computer,
            "kgarten": kgarten,
            "month_total": round(expected, 2),
            "paid": paid,
            "balance": new_balance,
            "month": month,
            "date": datetime.datetime.now(IST).replace(tzinfo=None),
            "payment_id": data["payment_id"],
            "order_id": data["order_id"],
            "remark": data.get("remarks", ""),
            "payment_mode": "Online"
        })

        master_col.update_one(
            {"adm_code": adm_code},
            {"$set": {
                "paid_fee": r.get("paid_fee", 0)+paid,
                "balance_fee": new_balance
            }}
        )

        return {"status": "success", "receipt_no": receipt_no}

    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.route("/logout")
def logout():
    session.pop("admission_code", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
