# Business tool functions

def get_current_offers():
    # Replace with actual business logic or database/API call
    # return "Current offers: 20% off on all diet plans, Buy 1 Get 1 Free on select items."
    return "Currently there are two offers available for 30 days --> \n1. Basic Plan Rs.2999  \n2. Advance Plan Rs.3999"

def get_diet_plans():
    # Replace with actual business logic or database/API call
    return "Diet Plans: Keto, Vegan, Mediterranean, Low-Carb. Contact us for personalized plans."

def place_order(order_details):
    # Replace with actual order placement logic
    return f"Order placed successfully! Details: {order_details}"

# Example Gemini tool definitions (for future Gemini tool calling API)
tools = [
    {
        "name": "get_current_offers",
        "description": "Get the latest offers and plans.",
        "parameters": {}
    },
    {
        "name": "get_diet_plans",
        "description": "Get available diet plans.",
        "parameters": {}
    },
    {
        "name": "place_order",
        "description": "Place an order for a plan or product.",
        "parameters": {"order_details": "Details of the order"}
    }
]
