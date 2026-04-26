# 15. Nexus 업로드 — 빠른 명령어 가이드

`loadtest-airgap-bundle-0.1.1.tar.gz`를 폐쇄망 호스트에서 Nexus Docker Repo에 올리는 최소 명령어 시퀀스. 모든 값은 실제 예시로 채워져 있습니다 (현장에 맞게 호스트/태그만 교체).

> 자세한 배경/스크립트 버전은 [09-nexus-upload-guide.md](09-nexus-upload-guide.md) 참조.

---

## 1. 번들 압축 해제

```bash
$ ls -lh /tmp/loadtest-airgap-bundle-0.1.1.tar.gz
-rw-r--r-- 1 user user 257M Apr 26 00:54 loadtest-airgap-bundle-0.1.1.tar.gz

$ cd /tmp
$ tar xzf loadtest-airgap-bundle-0.1.1.tar.gz
$ cd loadtest-airgap-bundle-0.1.1/image
$ ls
loadtest-tools-0.1.1.tar.gz  loadtest-tools-0.1.1.tar.gz.sha256
```

## 2. 무결성 검증

```bash
$ sha256sum -c loadtest-tools-0.1.1.tar.gz.sha256
loadtest-tools-0.1.1.tar.gz: OK
```

## 3. 이미지 로드

```bash
$ gunzip -c loadtest-tools-0.1.1.tar.gz | docker load
Loaded image: loadtest-tools:0.1.1

$ docker images loadtest-tools
REPOSITORY        TAG     IMAGE ID       CREATED        SIZE
loadtest-tools    0.1.1   a1b2c3d4e5f6   2 hours ago    1.05GB
```

## 4. Nexus 주소로 retag

```bash
$ docker tag loadtest-tools:0.1.1 nexus.intranet:8082/loadtest/loadtest-tools:0.1.1

$ docker images | grep loadtest-tools
loadtest-tools                                    0.1.1   a1b2c3d4e5f6   2 hours ago   1.05GB
nexus.intranet:8082/loadtest/loadtest-tools       0.1.1   a1b2c3d4e5f6   2 hours ago   1.05GB
```

## 5. Nexus 로그인

대화형:
```bash
$ docker login nexus.intranet:8082
Username: deployer
Password: ********
Login Succeeded
```

비대화형 (CI/스크립트):
```bash
$ echo 'MyN3xusP@ss' | docker login nexus.intranet:8082 -u deployer --password-stdin
Login Succeeded
```

## 6. push

```bash
$ docker push nexus.intranet:8082/loadtest/loadtest-tools:0.1.1
The push refers to repository [nexus.intranet:8082/loadtest/loadtest-tools]
5f70bf18a086: Pushed
ab4d1096d9ba: Pushed
...
0.1.1: digest: sha256:9c3a... size: 4521
```

## 7. 다른 노드에서 pull 검증

```bash
$ docker pull nexus.intranet:8082/loadtest/loadtest-tools:0.1.1
0.1.1: Pulling from loadtest/loadtest-tools
Status: Downloaded newer image for nexus.intranet:8082/loadtest/loadtest-tools:0.1.1

$ docker run --rm nexus.intranet:8082/loadtest/loadtest-tools:0.1.1 k6 version
k6 v0.55.0 (go1.22.5, linux/amd64)
```

## 8. K8s manifest 업데이트

```bash
$ cd deploy/load-testing

$ kustomize edit set image loadtest-tools=nexus.intranet:8082/loadtest/loadtest-tools:0.1.1

$ grep -A2 'images:' kustomization.yaml
images:
  - name: loadtest-tools
    newName: nexus.intranet:8082/loadtest/loadtest-tools
    newTag: "0.1.1"

$ kubectl --context=airgap-prod apply -k .
configmap/lt-config configured
job.batch/k6-promql configured
job.batch/opensearch-benchmark configured
...
```

## 9. 적용 확인

```bash
$ kubectl -n load-test get pods -o jsonpath='{range .items[*]}{.spec.containers[*].image}{"\n"}{end}' | sort -u
nexus.intranet:8082/loadtest/loadtest-tools:0.1.1
registry.k8s.io/pause:3.10
```

---

## 트러블슈팅 요약

| 증상 | 해결 |
|------|------|
| `denied: requested access to the resource is denied` | Nexus role에 `nx-repository-view-docker-loadtest-add/edit` 부여 |
| `unauthorized: authentication required` | `docker login` 다시 수행, `~/.docker/config.json` 확인 |
| `x509: certificate signed by unknown authority` | `/etc/docker/certs.d/nexus.intranet:8082/ca.crt`에 사내 CA 배치 후 `systemctl reload docker` |
| `413 Request Entity Too Large` | Nexus 앞단 nginx의 `client_max_body_size` 상향 |
| K8s `ImagePullBackOff` | imagePullSecret 누락, Nexus DNS 미해결 점검 |
