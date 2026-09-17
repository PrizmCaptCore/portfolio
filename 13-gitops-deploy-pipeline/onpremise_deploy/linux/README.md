# linux deploy

농산물(감자) 선별기 제품화 과정에서 온프레미스 배포를 위해 설계한 배포 인프라입니다.<br>
배포 타깃은 현장에 설치되는 엣지 디바이스이며, 이 디바이스는 시리얼/이더넷 프로토콜로 선별기 라인 컨트롤러와 통신합니다.<br>
따라서 지정된 디바이스에 한 번 설치된 뒤, 업데이트 루틴(패키지 교체)에 따라 갱신되는 형태의 상품입니다.<br>


# HOW TO USE
<br>

```
cp env/.env.example env/.env   # modify the value
./build.sh                     # → ./out/

#artifact form : <PKG_NAME>_<PKG_VERSION>_<PKG_ARCH>.deb
```
<br>

### ONLY TEST BUILD
#### IF YOU WANT TO BUILD YOUR APP's name hello.deb

<br>

```
docker build --target artifact --output type=local,dest=./out
```

<br>