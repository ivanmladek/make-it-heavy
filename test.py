

class Fruit:

    def __init__(self, name, color, taste):
        self.name = name
        self.color = color
        self.taste = taste

    def describe(self):
        return f"This is a {self.color} {self.name} and it tastes {self.taste}."

class Apple(Fruit):
    """
    Apples can be used to cook yummy dishes so we add an atribute for dishes to be 
    made out of only aples
    """

    def __init__(self, name, color, taste, dishes):
        super().__init__(name, color, taste)
        self.dishes = dishes

    def describe(self):
        return f"This is a {self.color} {self.name} and it tastes {self.taste}. It can be used to cook {self.dishes}."



if __name__ == "__main__":
    apple = Apple("apple", "red", "sweet", "apple pie")
    print(apple.describe())

    strawberry = Fruit("strawberry", "red", "sweet")
    print(strawberry.describe())



