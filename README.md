# S.PDF Web

**[S.PDF 바로 열기](https://junghangeul.github.io/s-pdf/)**

설치 없이 Edge나 Chrome에서 사용하는 PDF 작업 도구입니다. 기존 S.PDF의 파란색 작업 화면과 여러 문서 탭을 웹으로 옮겼습니다. 다른 컴퓨터에도 위 주소만 전달하면 됩니다.

PDF는 브라우저의 WebAssembly 작업 스레드에서 처리하며 서버에 업로드하지 않습니다. OCR 엔진과 한국어·영어 자료도 이 사이트에서 내려받아 기기 안에서 실행합니다. 외부 분석·광고·PDF 업로드 API를 사용하지 않습니다.

## 제공 기능

- 여러 PDF 탭과 각 문서의 페이지·확대 위치 유지
- 두 모서리를 클릭해 영역 선택, 마우스 위치에 따른 실시간 미리보기, Esc 취소
- 전체 페이지·선택 영역 150/300/600/1200/2400 dpi 및 가능한 최대 화질 자동 설정, 이미지 복사, 일괄 ZIP
- PDF 병합, 페이지 삭제·순서 변경·회전·추출·분할
- 기존 글자 한 줄 교체와 글자 추가, 한글 글꼴 포함
- 형광펜·사각형·화살표·메모, 검색, 북마크, 나란히 비교
- 실행 취소·다시 실행, 로컬 작업 복구, 밝은/어두운 화면
- 이미지 압축, 한국어·영어 OCR 검색층, 인쇄, 비밀번호 PDF 열기와 저장

편집 결과는 **새 PDF로 저장**으로 다운로드합니다. 원본 파일을 직접 덮어쓰지 않습니다. 작업 복구를 켜면 PDF 사본이 현재 브라우저의 IndexedDB에 남습니다. 공용 기기에서는 설정에서 끄거나 사본을 삭제하세요.

원본 글꼴·복잡한 글자 배치·세로쓰기는 완전히 재현하지 못할 수 있습니다. 글자 수정은 선택한 글꼴로 한 줄씩 반영되며 저장 전 확인이 필요합니다. 스캔 문서는 OCR 후 수정하거나 글자 추가를 이용할 수 있습니다. OCR 정확도는 원본 품질에 따라 달라집니다. PNG 저장은 구간별 렌더링으로 최대 2억4천만 화소까지 지원합니다. JPG와 클립보드 복사는 최대 6천만 화소이며, 한 변은 최대 32,000픽셀입니다. 한도를 넘는 요청은 가능한 최대 크기로 조절하며 실제 픽셀 크기와 dpi를 화면에 표시합니다. 큰 이미지 생성·붙여넣기 가능 여부는 기기의 메모리와 대상 앱에도 영향을 받습니다. PNG 파일이 300MB를 넘으면 영역을 나눠 저장해야 합니다. 인쇄는 페이지를 이미지로 준비합니다.

## 웹 업데이트와 배포

`web/`의 소스를 main에 반영하면 `Deploy S.PDF Web` 워크플로가 PDF 동작을 검증하고 GitHub Pages에 배포합니다. 별도의 설치나 재설치가 필요 없습니다. 배포가 끝난 후 새로 접속하거나 새로고침하면 새 버전이 열립니다. 열린 화면으로 돌아오면 새 버전 알림도 확인할 수 있습니다. 편집 중인 PDF는 먼저 다운로드하세요.

GitHub 저장소의 Settings → Pages → Source는 **GitHub Actions**로 설정합니다. 공개되는 것은 프로그램 소스와 정적 웹 파일이며 사용자 PDF·PPT 문서는 포함하지 않습니다. 예전 Windows 설치 파일은 과거 기록이며 현재 권장 배포 방식은 웹입니다. Windows 빌드는 수동 실행으로만 남겨두었습니다.

## 웹 개발과 검증

Python 3.12+ 및 Node.js 22+에서 다음 명령을 실행합니다. npm 설치 스크립트는 실행하지 않으며 고정된 라이브러리와 OCR 자료의 무결성을 검증합니다.

```sh
python fetch_ocr_models.py
python web/prepare_vendor.py
node --test web/tests/engine.test.mjs
python web/build.py
python -m http.server 8765 --directory web/dist
```

`http://localhost:8765/`를 엽니다. `web/vendor`와 `web/dist`는 생성물이며 Git에 넣지 않습니다. 선택적으로 Playwright를 준비한 환경에서 `node web/tests/browser.test.mjs`로 다운로드·편집·OCR·복구와 반응형 화면을 검사합니다. `SPDF_URL`로 테스트 주소를 지정할 수 있습니다. 테스트용 문서는 자체 생성하며 사용자 문서를 전송하지 않습니다.

소스: `web/engine.mjs`(PDF 처리), `web/pdf-worker.mjs`(직렬 작업), `web/app.mjs`(화면), `web/app.css`(디자인), `web/build.py`(정적 빌드). MuPDF는 AGPL-3.0으로 사용하며 전체 대응 소스는 이 저장소에 있습니다. 제3자 라이선스는 배포된 `vendor/`와 `assets/AGPL-3.0.txt`에서 확인할 수 있습니다.

## 과거 Windows 소스

아래는 예전 설치형 버전의 빌드 기록입니다.

## 실행과 빌드

Python 3.12에서 .venv 가상환경을 만들고 `requirements.txt`를 설치합니다.
`python fetch_ocr_models.py`로 고정된 버전의 한국어·영어 OCR 모델을 준비한 뒤 `main.py`를 실행합니다.
빌드 시 `build.ps1`을 실행합니다. `assets`의 승인된 아이콘과 Tesseract
`tessdata_fast`의 `kor.traineddata`, `eng.traineddata`를 함께 사용합니다.
배포본에는 Python/Qt/PDF 엔진과 OCR 언어 자료가 포함됩니다.
배포 시 표준 Python 실행 파일과 모듈을 분리해 동봉하고 작은 .NET 실행기를
사용합니다. PyInstaller는 의존성 수집에만 사용하며 동결 실행기는 배포하지 않습니다.

빌드 출력은 상위 폴더의 `output/S.PDF/S.PDF-Setup.exe`입니다.
원래의 간단한 뷰어 소스와 설치 파일은 별도로 보존합니다.
`prepare_build.py`는 버전 정보와 제3자 고지를 준비합니다.
소스 패키지만으로 다시 빌드할 때는 이미 생성된 `installer` 소스를 사용해도 됩니다.

## 구조

- `core.py`: 작업용 PDF 사본, 명령 기록, 안전한 저장, PDF 처리
- `canvas.py`: PDF 포인트 좌표의 화면과 영역 선택, 회전 좌표 변환
- `window.py`: 탭, 작업 공간, 검사 패널, 대화상자와 작업 흐름
- `main.py`: 실행, 사용자별 단일 인스턴스와 로컬 파일 전달
- `qa.py`: 별도 사용자 데이터와 offscreen Qt 플랫폼의 통합 검증

PyMuPDF는 스레드에 안전하지 않으므로 같은 문서의 작업은 GUI 스레드에서
직렬로 수행합니다. 긴 작업은 진행 상태를 표시하며, 여러 페이지 작업은
페이지 사이에서 취소할 수 있습니다. 실행 취소는 원본 작업 사본과 명령
기록을 재생하여 수행합니다. 2.1의 네이티브 journalling 텍스트 삽입 예외를
회피하며, 이미지가 많은 파일의 매 작업마다 전체 PDF를 복사하지 않습니다.

## 검증

`python -m pytest tests -q`

`python main.py --self-test --test-root <별도 폴더> [--sample <207페이지 PDF>]`

동일한 `--self-test`가 배포된 `S.PDF.exe`에서도 동작합니다. OS 화면·클립보드를
건드리지 않는 offscreen 플랫폼과 별도 데이터 폴더를 사용합니다.
설치 EXE의 `/extract <빈 폴더>`로 실제 설치 등록 없이 파일 구성을 검사할 수 있습니다.

텍스트 교체는 원래 텍스트를 지우고 선택한 시스템 글꼴로 삽입합니다.
원본의 복잡한 커닝·기울기·세로 배치는 그대로 재현하지 못할 수 있으며,
스캔 이미지의 글자 수정에는 선택 영역의 배경 지우기가 필요합니다.
OCR은 이미 있는 텍스트 페이지를 건너뛰며 이미지 페이지의 시각적 내용을
유지하고 검색용 텍스트를 추가합니다.

License: AGPL-3.0-or-later. Third-party notices and application source are shipped.
