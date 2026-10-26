#!/usr/bin/env python3
"""s3_backdate.py — 객체를 과거 시각(mtime)으로 다시 써서 ILM 일수 경과를 즉시 재현한다 (기한 만료 검증 E-*).

MinIO 는 사이트 복제용 내부 헤더 X-Minio-Source-Mtime 이 있으면 그 값을 객체 mtime 으로 쓴다
(복제 요청 헤더 + s3:ReplicateObject 권한 필요 — 관리자 키로만 실행). ILM 은 mtime 기준으로 일수를 센다.

사용:
  s3_backdate.py put <bucket> <key> <days_ago> [file]      # 새 객체를 N일 전 mtime 으로 PUT
  s3_backdate.py rewrite <bucket> <prefix> <days_ago>      # prefix 아래 current 객체를 같은 내용으로 다시 PUT
                                                           # (Versioning ON 이면 원본 버전은 영구 삭제 — 시험 데이터 전용)
  s3_backdate.py head <bucket> <key>
자격증명: MC_HOST_<ALIAS>(기본 HOT) 환경변수 http(s)://AK:SK@host:port — 출력하지 않는다.
표준 라이브러리만 사용 (폐쇄망).
"""
import datetime
import hashlib
import hmac
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ALIAS = os.environ.get("BACKDATE_ALIAS", "HOT")
u = urllib.parse.urlparse(os.environ["MC_HOST_" + ALIAS])
AK, SK = urllib.parse.unquote(u.username), urllib.parse.unquote(u.password)
EP = "{}://{}".format(u.scheme, u.hostname + (":{}".format(u.port) if u.port else ""))
HOST = urllib.parse.urlparse(EP).netloc
REGION = os.environ.get("AWS_REGION", "us-east-1")


def sign(method, path, query, headers, body):
    now = datetime.datetime.utcnow()
    amz, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    ph = hashlib.sha256(body).hexdigest()
    h = {k.lower(): v for k, v in headers.items()}
    h.update({"host": HOST, "x-amz-date": amz, "x-amz-content-sha256": ph})
    sh = sorted(h)
    canon_q = "&".join("{}={}".format(urllib.parse.quote(k, safe="-_.~"), urllib.parse.quote(v, safe="-_.~"))
                       for k, v in sorted(query.items()))
    creq = "\n".join([method, urllib.parse.quote(path, safe="/-_.~"), canon_q,
                      "".join("{}:{}\n".format(k, str(h[k]).strip()) for k in sh), ";".join(sh), ph])
    scope = "{}/{}/s3/aws4_request".format(day, REGION)
    sts = "\n".join(["AWS4-HMAC-SHA256", amz, scope, hashlib.sha256(creq.encode()).hexdigest()])
    k = ("AWS4" + SK).encode()
    for p in (day, REGION, "s3", "aws4_request"):
        k = hmac.new(k, p.encode(), hashlib.sha256).digest()
    sig = hmac.new(k, sts.encode(), hashlib.sha256).hexdigest()
    h["authorization"] = "AWS4-HMAC-SHA256 Credential={}/{}, SignedHeaders={}, Signature={}".format(AK, scope, ";".join(sh), sig)
    return h, canon_q


def req(method, path, query=None, headers=None, body=b""):
    h, q = sign(method, path, query or {}, headers or {}, body)
    r = urllib.request.Request(EP + urllib.parse.quote(path, safe="/-_.~") + ("?" + q if q else ""),
                               data=body if method in ("PUT", "POST") else None, method=method, headers=h)
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def put(bucket, key, days_ago, body):
    mtime = (datetime.datetime.utcnow() - datetime.timedelta(days=float(days_ago))).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    st, h, b = req("PUT", "/{}/{}".format(bucket, key), headers={
        "X-Minio-Source-Mtime": mtime, "X-Minio-Source-Replication-Request": "true"}, body=body)
    return st, h.get("x-amz-version-id"), b[:300]


def list_keys(bucket, prefix):
    keys, token = [], None
    while True:
        q = {"list-type": "2", "prefix": prefix}
        if token:
            q["continuation-token"] = token
        st, _, b = req("GET", "/" + bucket, q)
        root = ET.fromstring(b)
        ns = {"s": root.tag.split("}")[0].strip("{")}
        keys += [c.find("s:Key", ns).text for c in root.findall("s:Contents", ns)]
        if root.findtext("s:IsTruncated", namespaces=ns) != "true":
            return keys
        token = root.findtext("s:NextContinuationToken", namespaces=ns)


def main():
    cmd = sys.argv[1]
    if cmd == "put":
        body = open(sys.argv[5], "rb").read() if len(sys.argv) > 5 else b"ilm-age-test\n"
        print(put(sys.argv[2], sys.argv[3], sys.argv[4], body))
    elif cmd == "rewrite":
        bucket, prefix, days = sys.argv[2], sys.argv[3], sys.argv[4]
        n = 0
        for k in list_keys(bucket, prefix):
            st, h, body = req("GET", "/{}/{}".format(bucket, k))
            if st != 200:
                print("GET", k, st)
                continue
            orig = h.get("x-amz-version-id")
            st, vid, err = put(bucket, k, days, body)
            if st != 200:
                print("PUT", k, st, err)
                sys.exit(1)
            # 버전 순서는 mtime 기준이라 과거 mtime 버전은 '이전 버전'으로 들어간다 → 원본 버전을 영구 삭제해 최신으로 만든다
            if orig and orig != "null" and orig != vid:
                st, _, err = req("DELETE", "/{}/{}".format(bucket, k), {"versionId": orig})
                if st not in (200, 204):
                    print("DELETE", k, orig, st, err[:200])
                    sys.exit(1)
            n += 1
        print("rewritten", n, "objects under", prefix, "as", days, "days ago")
    elif cmd == "head":
        st, h, _ = req("HEAD", "/{}/{}".format(sys.argv[2], sys.argv[3]))
        print(st, h.get("Last-Modified"), h.get("x-amz-storage-class"), h.get("x-amz-version-id"))


if __name__ == "__main__":
    main()
