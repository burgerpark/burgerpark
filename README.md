# COM-IP Bridge

VSP3 스타일의 멀티포트 COM(시리얼) ↔ TCP/IP 브릿지 프로그램

## 주요 기능

- **멀티포트 지원**: 여러 개의 COM-IP 브릿지를 동시에 운영
- **TCP Server / Client / UDP 모드**: VSP3와 동일한 연결 모드
- **시리얼 포트 전체 설정**: Baud Rate, Data Bits, Stop Bits, Parity, Flow Control
- **자동 재연결**: 연결 끊김 시 자동 복구 (간격 설정 가능)
- **Lazy Connect**: 데이터 발생 시에만 TCP 연결 (Connect on Data)
- **비활성 타임아웃**: 일정 시간 데이터 없으면 자동 연결 해제
- **데이터 모니터**: 실시간 Hex/ASCII 데이터 모니터 (색상 구분)
- **설정 영구 저장**: JSON 파일로 설정 자동 저장/로드
- **설정 내보내기/가져오기**: 다른 PC로 설정 이동 가능
- **시스템 트레이**: 최소화 시 트레이로 이동, 백그라운드 실행
- **RFC 2217 지원**: Telnet COM Port Control 프로토콜

## 빌드 방법

### 요구사항
- .NET 8.0 SDK (Windows)
- Windows 10/11

### 빌드
```bash
dotnet build src/ComIpBridge.csproj -c Release
```

### 실행
```bash
dotnet run --project src/ComIpBridge.csproj
```

### 단일 실행 파일 배포
```bash
dotnet publish src/ComIpBridge.csproj -c Release -r win-x64 --self-contained
```

### 설치 파일 생성 (Inno Setup)

#### 방법 1: 원클릭 빌드 스크립트
```bash
# CMD
build.bat

# PowerShell
.\build.ps1
```

#### 방법 2: 수동
1. [Inno Setup 6](https://jrsoftware.org/isdl.php) 설치
2. `dotnet publish` 로 빌드
3. Inno Setup에서 `installer/setup.iss` 열고 컴파일
4. `installer/Output/ComIpBridge_Setup_v1.0.0.exe` 생성됨

### 설치 옵션
- 바탕화면 바로가기
- Windows 시작 시 자동 실행
- `.combridge` 파일 연결 (설정 파일 더블클릭으로 열기)

## 사용법

1. **Add Port** 버튼으로 새 브릿지 포트 추가
2. COM 포트, IP, TCP 포트, 연결 모드 설정
3. **Start** 버튼으로 브릿지 시작
4. 하단 데이터 모니터에서 실시간 데이터 확인

## VSP3 대비 개선점

| 기능 | VSP3 | COM-IP Bridge |
|------|------|---------------|
| 동시 포트 수 | 제한적 | 무제한 |
| 설정 내보내기 | X | O (JSON) |
| 데이터 모니터 | 별도 | 내장 |
| UDP 모드 | 제한적 | 완전 지원 |
| 오픈소스 | X | O |

## 프로젝트 구조

```
src/
├── Core/
│   ├── SerialBridge.cs      # 핵심 브릿지 엔진
│   └── BridgeManager.cs     # 멀티포트 관리자
├── Models/
│   ├── BridgeConfig.cs      # 브릿지 설정 모델
│   ├── BridgeStatus.cs      # 상태 모델
│   └── LogEntry.cs          # 로그 모델
├── UI/
│   ├── MainForm.cs          # 메인 윈도우
│   ├── PortConfigDialog.cs  # 포트 설정 다이얼로그
│   └── DataMonitorPanel.cs  # 데이터 모니터
├── Utils/
│   └── ConfigManager.cs     # 설정 저장/로드
└── Program.cs               # 진입점
```
