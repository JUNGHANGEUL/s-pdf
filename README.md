# S.PDF

**[Windows 설치 파일 다운로드](https://github.com/JUNGHANGEUL/s-pdf/releases/latest/download/S.PDF-Setup.exe)**

Windows 10/11 x64용 PDF 뷰어 및 편집기입니다. PDF는 컴퓨터 안에서 처리합니다.
설치 후에는 실행할 때 GitHub에서 새 버전을 확인하고, 다운로드와 SHA256 검증을
마친 뒤 문서를 닫고 종료할 때 적용합니다. 인터넷에 연결되지 않아도 기존 버전을
계속 사용할 수 있습니다. 메뉴에서 자동 업데이트 설정과 직접 확인을 제공합니다.

## 새 버전 배포

`version.py`의 VERSION을 올리고 변경사항을 main에 푸시하면 GitHub Actions가
테스트, Windows 설치 파일 생성, 실제 배포본 확인을 수행한 후 Releases에 올립니다.
동일한 버전의 공개 릴리스는 덮어쓰지 않습니다. 작업 중인 코드를 수정하는 것만으로
다른 컴퓨터에 반영되지 않으며 검증된 새 릴리스를 배포해야 합니다.

배포 파일: S.PDF-Setup.exe, update.json, SHA256.txt, S.PDF_Source.zip, 사용방법.txt.
소스와 설치 파일을 공개하는 저장소이며 사용자 PDF·PPT 문서는 포함하지 않습니다.

승인된 S.PDF 디자인을 적용한 Windows 10/11 x64용 로컬 PDF 편집기입니다.
다중 탭, 전체·영역·일괄 고화질 캡처, 클립보드, 병합, 삭제, 추출, 분할,
순서 변경, 회전, 실제 텍스트 교체와 추가, 주석, 검색, 북마크, 비교,
동기 스크롤, 인쇄, 실행 취소/재실행, 자동 복구, 압축, 한국어 OCR를 제공합니다.

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
