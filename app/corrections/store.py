"""复算更正与证据版本的持久化。

- corrections：每份休港补证一条，doc_id 保证重跑同一份补证幂等。
- correction_entries：按箱保存原账、现账与记账差额，供累计守恒核对。
- correction_evidence：每次成功签发后固化证据，旧版本原样可下载。
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone


class CorrectionStore:
    def __init__(self, path):
        self.path = path
        self.init()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=8)
        connection.row_factory = sqlite3.Row
        return connection

    def init(self):
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS corrections(
              id TEXT PRIMARY KEY,
              run_id TEXT NOT NULL,
              doc_id TEXT NOT NULL,
              request_key TEXT UNIQUE NOT NULL,
              created_at TEXT NOT NULL,
              status TEXT NOT NULL,
              revision INTEGER NOT NULL DEFAULT 0,
              expected_run_revision INTEGER NOT NULL,
              applied_run_revision INTEGER,
              comment TEXT NOT NULL DEFAULT '',
              plan TEXT NOT NULL,
              payload TEXT NOT NULL,
              UNIQUE(run_id, doc_id)
            );
            CREATE TABLE IF NOT EXISTS correction_entries(
              correction_id TEXT NOT NULL,
              container_id TEXT NOT NULL,
              action TEXT NOT NULL,
              original_fee_cents INTEGER NOT NULL,
              current_fee_cents INTEGER NOT NULL,
              booking_delta_cents INTEGER NOT NULL,
              detail TEXT NOT NULL,
              PRIMARY KEY(correction_id, container_id)
            );
            CREATE TABLE IF NOT EXISTS correction_evidence(
              run_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              correction_id TEXT,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              artifact TEXT NOT NULL,
              digest TEXT NOT NULL,
              PRIMARY KEY(run_id, version)
            );
            ''')

    @staticmethod
    def request_key(run_id, doc_id):
        return hashlib.sha256((run_id + "|" + doc_id).encode("utf-8")).hexdigest()[:32]

    def find_doc(self, run_id, doc_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM corrections WHERE run_id=? AND doc_id=?",
                             (run_id, doc_id)).fetchone()
        return dict(row) if row else None

    def find_request(self, request_key):
        with self.connect() as db:
            row = db.execute("SELECT * FROM corrections WHERE request_key=?", (request_key,)).fetchone()
        return dict(row) if row else None

    def create_draft(self, run_id, doc_id, expected_run_revision, plan, payload):
        request_key = self.request_key(run_id, doc_id)
        existing = self.find_request(request_key)
        if existing:
            return existing, False
        correction_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute(
                "INSERT INTO corrections(id,run_id,doc_id,request_key,created_at,status,"
                "expected_run_revision,plan,payload) VALUES(?,?,?,?,?,?,?,?,?)",
                (correction_id, run_id, doc_id, request_key, now, "DRAFT",
                 expected_run_revision, json.dumps(plan, ensure_ascii=False),
                 json.dumps(payload, ensure_ascii=False)))
            db.executemany(
                "INSERT INTO correction_entries(correction_id,container_id,action,"
                "original_fee_cents,current_fee_cents,booking_delta_cents,detail) VALUES(?,?,?,?,?,?,?)",
                [(correction_id, entry["container_id"], entry["action"],
                  entry["original_fee_cents"], entry["current_fee_cents"],
                  entry["booking_delta_cents"], json.dumps(entry, ensure_ascii=False))
                 for entry in plan["entries"]])
        return self.get(correction_id), True

    def get(self, correction_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM corrections WHERE id=?", (correction_id,)).fetchone()
        return dict(row) if row else None

    def list_for_run(self, run_id):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM corrections WHERE run_id=? ORDER BY created_at", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def entries(self, correction_id):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM correction_entries WHERE correction_id=? ORDER BY container_id",
                              (correction_id,)).fetchall()
        return [dict(row) for row in rows]

    def approved_deltas(self, run_id):
        """已签发更正中每个箱子的累计记账差额。"""
        with self.connect() as db:
            rows = db.execute(
                "SELECT container_id, SUM(booking_delta_cents) AS delta FROM correction_entries e "
                "JOIN corrections c ON c.id = e.correction_id "
                "WHERE c.run_id=? AND c.status='APPROVED' GROUP BY container_id",
                (run_id,)).fetchall()
        return {row["container_id"]: int(row["delta"] or 0) for row in rows}

    def approve(self, run_id, correction_id, decision, comment, expected_revision,
                run_revision, plan, artifact, digest):
        """在一个事务内完成更正签发与运行版本推进，失败则整体保留旧版。"""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM corrections WHERE id=?", (correction_id,)).fetchone()
            if row is None:
                return None, "missing"
            if row["run_id"] != run_id:
                return None, "missing"
            if row["revision"] != expected_revision:
                return None, "stale"
            run = db.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if run is None:
                return None, "run_missing"
            if run["revision"] != row["expected_run_revision"]:
                return None, "run_stale"
            new_run_revision = run["revision"] + 1
            version = new_run_revision
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                "UPDATE corrections SET status=?, revision=revision+1, comment=?, applied_run_revision=? WHERE id=?",
                (decision, comment.strip(), new_run_revision if decision == "APPROVED" else None, correction_id))
            if decision == "APPROVED":
                db.execute("UPDATE runs SET revision=? WHERE id=?", (new_run_revision, run_id))
                db.execute(
                    "INSERT INTO correction_evidence(run_id,version,correction_id,status,created_at,artifact,digest)"
                    " VALUES(?,?,?,?,?,?,?)",
                    (run_id, version, correction_id, "APPROVED", now,
                     json.dumps(artifact, ensure_ascii=False), digest))
        return self.get(correction_id), None

    def save_base_evidence(self, run_id, artifact, digest):
        """原批次签发证据固化为 version 1（若尚未固化）。"""
        with self.connect() as db:
            exists = db.execute("SELECT 1 FROM correction_evidence WHERE run_id=? AND version=1",
                                (run_id,)).fetchone()
            if exists:
                return
            now = datetime.now(timezone.utc).isoformat()
            db.execute(
                "INSERT INTO correction_evidence(run_id,version,correction_id,status,created_at,artifact,digest)"
                " VALUES(?,?,?,?,?,?,?)",
                (run_id, 1, None, "APPROVED", now,
                 json.dumps(artifact, ensure_ascii=False), digest))

    def get_evidence(self, run_id, version):
        with self.connect() as db:
            row = db.execute("SELECT * FROM correction_evidence WHERE run_id=? AND version=?",
                             (run_id, version)).fetchone()
        return dict(row) if row else None

    def list_evidence(self, run_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT run_id,version,correction_id,status,created_at,digest FROM correction_evidence "
                "WHERE run_id=? ORDER BY version", (run_id,)).fetchall()
        return [dict(row) for row in rows]

    def latest_version(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT MAX(version) AS v FROM correction_evidence WHERE run_id=?",
                             (run_id,)).fetchone()
        return row["v"]
