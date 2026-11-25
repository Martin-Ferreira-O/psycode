from django.db.models import TextChoices

JEV_DEFAULT_THRESHOLD = 0.55
SPEECHMATICS_MODEL_ID_MAX_LENGTH = 80
SPEECHMATICS_MODEL_ID_PATTERN = r"\A[a-z0-9]+(?:[._-][a-z0-9]+)*\Z"


class JevVersion(TextChoices):
    V114 = "1.14", "Jev 1.14"
    V113 = "1.13", "Jev 1.13"

    @property
    def typesafe_id(self):
        return f"jev-{self.value}.0"

    @property
    def openrouter_id(self):
        return f"typesafe/jev-{self.value}"


class SpeechmaticsModel(TextChoices):
    ENHANCED = "enhanced", "Enhanced"
    STANDARD = "standard", "Standard"
    MELIA = "melia-1", "Melia 1"
    OAK = "oak-1", "Oak 1 Medical"
