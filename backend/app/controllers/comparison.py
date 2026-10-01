from app.services.comparison import comparison_service


def comparison_controller(session, model_id, segment, country):
    return comparison_service(session, model_id, segment, country)
