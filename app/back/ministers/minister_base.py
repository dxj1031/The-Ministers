# Base class for all ministers in the application (reusable modular tools)
class Minister:
    def __init__(self, name, defect, influence_weight, role):
        self.name = name
        self.defect = defect
        self.influence_weight = influence_weight
        self.role = role

    def get_info(self):
        return f"Minister {self.name} has a {self.defect} defect and an influence weight of {self.influence_weight}."
    
    def think(self, problem):
        return f"{self.name} is thinking about {problem} with a {self.defect} approach."
    
    def write_wiki(self, content):
        # TODO:
        # Move wiki writing to memory layer, Responsibility Separation
        return f"{self.name} is writing a wiki entry about {content} with a {self.defect} approach."
    
    def read_wiki(self, content):
        return f"{self.name} is reading the wiki entry about {content} with a {self.defect} approach."
    
    def speak(self, message):
        return f"{self.name} is speaking about {message} with a {self.defect} approach."
    
    def listen(self, message):
        return f"{self.name} is listening to {message} with a {self.defect} approach."