import tkinter as tk

def basic_page():
    root = tk.Tk()
    root.title("Basic Page")
    root.geometry("400x300")

    label = tk.Label(root, text="Welcome to the Basic Page!", font=("Arial", 16))
    label.pack(pady=20)

    button = tk.Button(root, text="Click Me", command=lambda: print("Button Clicked!"))
    button.pack(pady=10)

    root.mainloop()

if __name__ == "__main__":
    basic_page()