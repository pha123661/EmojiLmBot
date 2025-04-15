
class CommandParser:
    def __init__(self, keywords):
        self.keywords = keywords

    def startswith_keyword(self, text):
        for keyword in self.keywords:
            if text.startswith(keyword):
                return text[len(keyword):]
        return None

    def endswith_keyword(self, text):
        for keyword in self.keywords:
            if text.endswith(keyword):
                return text[:-len(keyword)]
        return None

    def startswith_or_endswith_keyword(self, text):
        for keyword in self.keywords:
            if text.startswith(keyword):
                return text[len(keyword):]
            elif text.endswith(keyword):
                return text[:-len(keyword)]
        return None

    def only_keyword(self, text):
        for keyword in self.keywords:
            if text == keyword:
                return True
        return False