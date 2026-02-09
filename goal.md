connection.md에  kubernetes 클러스터 접속하여 kubectl 사용
opensearch + fluent-bit operator helm value.yaml 로 배포 

목표 
fluent-bit 로  appilication log , java log4j json format log 수집을 위해 컨테이너 로그가 아닌 hostpath를 사용하여 
서비스팀별열 작업추적 정보를 수집하여 파이프라인을 구성하려고 하는데 사용자들이 kubernetes를 잘 몰라서 상세한 yaml설정가이드가 필요해. 

yaml은 어떻게 작성해야 하는지 hostpath에 log write가 안써진다던지, 권한이 없어서 폴더가 안생겨요, /var/log/{namespace}/ 에 로그가 없어요 등 , 문의가 너무 많이 들어와서 , 내가 직접 구성해보고 결과를 낸다음 가이드를 할려고 해, 

특히 spec의 volume volumemount 등 관련 설정 및 옵션에 대해서도 너무 헷갈려 하는데  일단 확실하게 데이터 파이프라인을 구성하고 fluent-bit operator json multiline내 내장 파서를 쓸때 input , ouput 의 버퍼 등 설정문제로 대량로그 emiiter 시 OOM으로 지속적인 문제에 대한 실제 구축 설정 및 튜닝 가이드도 필요해     