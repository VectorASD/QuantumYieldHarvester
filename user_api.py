"""Interactive user input helpers for JSON data"""

from pathlib import Path
import json

json_value = dict | list | str | int | float | bool | None
# nevertheless I will write an annotation like: "json_value | None",
# implying that json itself can contain "null",
# and the function itself can return an empty return


class User:
    @staticmethod
    def get_number(header: str, prompt: str, valid_options: set[int] | list[int] | tuple[int] | range) -> int | None:
        """Ask the user for a number until it is one of valid_options"""
        print(header)
        while True:
            try:
                number = int(input(prompt).strip())
                if number in valid_options:
                    return number
                print(f"Please enter one of: {sorted(valid_options)}")
            except ValueError:
                print("Invalid input, please enter a number")
            except KeyboardInterrupt:
                print("\nCancelled")
                return

    @staticmethod
    def get_file_path_manual() -> Path | None:
        """Ask user to type file path until an existing file is given or user exits"""
        while True:
            try:
                raw = input("Enter path to JSON file (or Ctrl+C to quit): ").strip()
                if not raw:
                    print("Empty path, try again")
                    continue
                path = Path(raw)
                if path.exists():
                    return path
                print(f"File not found: {path}")
            except KeyboardInterrupt:
                print("\nCancelled")
                return

    @staticmethod
    def get_filepath_tk(title: str, *filetypes: tuple[str, str]) -> Path | None:
        """Try to open file dialog with tkinter, return selected path or None"""
        try:
            import tkinter as tk
            from tkinter import filedialog
        except ImportError:
            # fallback: tkinter unavailable
            return User.get_file_path_manual()

        try:
            root = tk.Tk()
            root.withdraw()
            file_path = filedialog.askopenfilename(title=title, filetypes=filetypes)
            root.destroy()
            if file_path:
                return Path(file_path)
            return
        except KeyboardInterrupt:
            return
        except Exception:
            # If dialog fails for any reason, return None to trigger fallback
            return User.get_file_path_manual()

    @staticmethod
    def get_json_manual() -> json_value | None:
        """Ask user to paste JSON as a single line and parse it"""
        while True:
            try:
                raw = input("Paste JSON (single line): ").strip()
                if not raw:
                    print("No JSON provided. Try again or Ctrl+C to cancel")
                    continue
                return json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"Invalid JSON: {e}")
            except KeyboardInterrupt:
                return

    @staticmethod
    def get_json_tk(title: str, *filetypes: tuple[str, str]) -> json_value | None:
        """Ask user to select a JSON file via dialog (or manual fallback) and parse it"""
        while True:
            try:
                path = User.get_filepath_tk(title, *filetypes)
                if path is None:
                    print("No file selected")
                    return
                with open(path, 'r', encoding="utf-8") as file:
                    return json.load(file)
            except json.JSONDecodeError as e:
                print(f"Invalid JSON: {e}")

    @staticmethod
    def get_json(main_title: str, tk_title: str) -> json_value | None:
        """Ask user to provide JSON either by pasting text or selecting a file"""
        print("=" * 77)
        print(main_title)
        print("=" * 77)

        while True:
            mode = User.get_number(
                "Choose input method:\n1 - paste JSON manually\n2 - select file\n3 - exit (Ctrl+C)",
                "Enter number: ",
                range(1, 4)
            )
            if mode is None:
                return
            if mode == 1:
                result = User.get_json_manual()
                if result is not None:
                    return result
            if mode == 2:
                result = User.get_json_tk(
                    tk_title,
                    ("JSON files", "*.json"),
                    ("All files", "*.*")
                )
                if result is not None:
                    return result
            if mode == 3:
                return


if __name__ == "__main__":
    obj = User.get_json(
        "Create OAuth client ID: https://console.cloud.google.com/auth/clients/create\nApplication type: Desktop app",
        "Select Google OAuth client JSON"
    )
    print("result:", obj)
