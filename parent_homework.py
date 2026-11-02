
from flask import Blueprint, request, jsonify, current_app
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from db import master_col, homework_collection

homework_bp = Blueprint("parent_homework", __name__)

TOKEN_SALT = "parent-homework"
TOKEN_MAX_AGE = 30 * 24 * 60 * 60


def verify_parent():
    auth = request.headers.get("Authorization", "").strip()

    if not auth.startswith("Bearer "):
        return None

    token = auth.split(" ", 1)[1].strip()

    if not token:
        return None

    try:
        serializer = URLSafeTimedSerializer(
            current_app.secret_key,
            salt=TOKEN_SALT
        )

        data = serializer.loads(token, max_age=TOKEN_MAX_AGE)

        if not isinstance(data, dict):
            return None

        adm = str(data.get("adm_code", "")).strip().upper()

        if not adm:
            return None

        return master_col.find_one({"adm_code": adm})

    except (BadSignature, SignatureExpired):
        return None


@homework_bp.route("/api/parent/homework", methods=["GET"])
def parent_homework():
    try:
        if master_col is None or homework_collection is None:
            return jsonify(
                success=False,
                message="Database unavailable"
            ), 503

        student = verify_parent()

        if not student:
            return jsonify(
                success=False,
                message="Invalid or expired login. Please login again."
            ), 401

        student_class = str(student.get("class", "")).strip()
        section = str(
            student.get("sec") or student.get("section") or ""
        ).strip()

        if not student_class:
            return jsonify(
                success=False,
                message="Student class not found"
            ), 404

        query = {
            "class": student_class,
            "$or": [
                {"section": section},
                {"section": ""},
                {"section": None},
                {"section": {"$exists": False}}
            ]
        }

        records = homework_collection.find(query).sort([
            ("given_date", -1),
            ("created_at", -1)
        ])

        result = []

        for h in records:
            result.append({
                "subject": h.get("subject", ""),
                "homework": h.get(
                    "homework",
                    h.get("description", h.get("homework_text", ""))
                ),
                "given_date": h.get("given_date", ""),
                "due_date": h.get("due_date", ""),
                "class": h.get("class", ""),
                "section": h.get("section", "")
            })

        return jsonify({
            "success": True,
            "student_name": student.get("student_name", ""),
            "class_name": student_class,
            "section": section,
            "count": len(result),
            "homework": result
        }), 200

    except Exception:
        current_app.logger.exception("Parent homework API error")

        return jsonify(
            success=False,
            message="Unable to load homework"
        ), 500
