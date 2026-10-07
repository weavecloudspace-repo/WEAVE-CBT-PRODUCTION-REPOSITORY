"""Current academic-period boundary for makeup authorization."""

from app.domains.academics.repository import AcademicRepository


async def require_current_makeup_term(db, exam):
    session = await AcademicRepository.get_current_session(db)
    term = (
        await AcademicRepository.get_current_term(db, session_id=session.id)
        if session
        else None
    )
    if (
        session is None
        or term is None
        or exam.session_id != session.id
        or exam.term_id != term.id
    ):
        raise ValueError(
            "Makeup access is only available for the current academic session and term"
        )
