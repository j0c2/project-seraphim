from ts.torch_handler.base_handler import BaseHandler


class CustomTextHandler(BaseHandler):
    def initialize(self, context):
        # No model weights needed for the dummy example
        self.initialized = True

    def preprocess(self, data):
        text = data[0].get("body")
        if isinstance(text, (bytes, bytearray)):
            text = text.decode("utf-8")
        return text

    def inference(self, text, *args, **kwargs):
        # Dummy model logic: positive if even length
        return {"prediction": "positive" if len(text) % 2 == 0 else "negative"}

    def postprocess(self, inference_output):
        return [inference_output]
