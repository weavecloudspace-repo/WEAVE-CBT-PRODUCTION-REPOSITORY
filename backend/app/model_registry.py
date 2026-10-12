"""Import every SQLAlchemy model module for metadata registration."""

from app.domains.academics import models as academics_models  # noqa: F401
from app.domains.attempts import models as attempts_models  # noqa: F401
from app.domains.audit import models as audit_models  # noqa: F401
from app.domains.auth import models as auth_models  # noqa: F401
from app.domains.auth import student_models as student_auth_models  # noqa: F401
from app.domains.branding import models as branding_models  # noqa: F401
from app.domains.candidates import models as candidates_models  # noqa: F401
from app.domains.exams import execution_models as exam_execution_models  # noqa: F401
from app.domains.exams import models as exams_models  # noqa: F401
from app.domains.media import models as media_models  # noqa: F401
from app.domains.questions import ai_models as question_ai_models  # noqa: F401
from app.domains.questions import models as questions_models  # noqa: F401
from app.domains.results import models as results_models  # noqa: F401
from app.domains.runtime import models as runtime_models  # noqa: F401
from app.domains.sync import models as sync_models  # noqa: F401
