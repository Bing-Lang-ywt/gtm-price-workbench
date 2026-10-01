from app.services.feedback import (
    create_feedback_service,
    delete_feedback_service,
    list_feedbacks_service,
)


def list_controller(session, page, limit):
    return list_feedbacks_service(session, page, limit)


def create_controller(session, payload):
    return create_feedback_service(session, payload)


def delete_controller(session, feedback_id):
    return delete_feedback_service(session, feedback_id)
