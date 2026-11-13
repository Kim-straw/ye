"""테스트가 실제 app.db를 지우지 않도록, 테스트 전용 임시 DB 파일을 쓰게 함.
(app 모듈을 불러오기 전에 설정해야 하므로 여기에 둠)"""
import os
import tempfile

os.environ["SPEC_DB"] = os.path.join(tempfile.mkdtemp(prefix="specroad-test-"), "test.db")
