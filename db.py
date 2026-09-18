# db.py
import os
from pymongo import MongoClient, errors

LOCAL_URI = "mongodb://localhost:27017/"

MONGO_URI = os.getenv("MONGO_URI", LOCAL_URI)

master_collection = None
counters_collection = None
users_collection = None
students_collection = None
transport_collection = None
tran_collection = None

tran_col = None
master_col = None

try:
    client = MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000
    )

    client.admin.command("ping")
    print("MongoDB Connected Successfully")

    # SCHOOL DATABASE
    school_db = client["school_db"]
    master_collection = school_db["master"]
    counters_collection = school_db["counters"]
    users_collection = school_db["users"]
    students_collection = school_db["students"]

    # TRANSPORT DATABASE
    transport_db = client["transport_db"]
    transport_collection = transport_db["stand_name"]

    # TRANSACTION DATABASE
    tran_db = client["tran"]
    tran_collection = tran_db["transactions"]

    # Aliases
    tran_col = tran_collection
    master_col = master_collection

    master = master_collection
    counters = counters_collection
    transport = transport_collection
    tran = tran_collection

    try:
        tran_collection.create_index(
            [("adm_code", 1), ("month", 1)],
            unique=True
        )
        print("Transaction index verified")
    except Exception as e:
        print(f"Index creation skipped: {e}")

except errors.ServerSelectionTimeoutError as e:
    print(f"MongoDB connection failed: {e}")

except Exception as e:
    print(f"Unexpected MongoDB error: {e}")
