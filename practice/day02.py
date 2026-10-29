"""Small Python exercises for the Abacus project setup."""


def fizzbuzz(n: int) -> list[str]:
    """Return FizzBuzz labels for the integers from 1 through n."""
    if n < 0:
        raise ValueError("n must be non-negative")

    result = []
    for number in range(1, n + 1):
        if number % 15 == 0:
            result.append("FizzBuzz")
        elif number % 3 == 0:
            result.append("Fizz")
        elif number % 5 == 0:
            result.append("Buzz")
        else:
            result.append(str(number))
    return result


def reverse_text(text: str) -> str:
    """Return text in reverse order using a loop."""
    reversed_text = ""
    for character in text:
        reversed_text = character + reversed_text
    return reversed_text


def total(numbers: list[int]) -> int:
    """Add the numbers without using the built-in sum function."""
    result = 0
    for number in numbers:
        result += number
    return result


def largest(numbers: list[int]) -> int:
    """Return the largest number; raise ValueError for an empty list."""
    if not numbers:
        raise ValueError("largest() needs at least one number")

    result = numbers[0]
    for number in numbers[1:]:
        if number > result:
            result = number
    return result


def word_counts(text: str) -> dict[str, int]:
    """Count whitespace-separated words, preserving case and punctuation."""
    counts: dict[str, int] = {}
    for word in text.split():
        counts[word] = counts.get(word, 0) + 1
    return counts


def main() -> None:
    """Print normal and boundary examples for each exercise."""
    print("fizzbuzz(15):", fizzbuzz(15))
    print("fizzbuzz(0):", fizzbuzz(0))
    print("reverse_text('Abacus'):", reverse_text("Abacus"))
    print("reverse_text(''):", reverse_text(""))
    print("total([2, -1, 4]):", total([2, -1, 4]))
    print("total([]):", total([]))
    print("largest([2, -1, 4]):", largest([2, -1, 4]))
    try:
        largest([])
    except ValueError as error:
        print("largest([]):", error)
    print("word_counts('a b a'):", word_counts("a b a"))
    print("word_counts(''):", word_counts(""))


if __name__ == "__main__":
    main()
