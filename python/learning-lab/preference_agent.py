from schemas import TravelRequest


class PreferenceAgent:
    def run(self, preferences: TravelRequest) -> TravelRequest:
        result = preferences.model_copy(deep=True)

        if not result.interests:
            result.interests = ["经典景点", "当地美食"]

        return result