import argparse
from utils import add, sub, mul, div

def main():
    parser = argparse.ArgumentParser(description="Simple Calculator")
    parser.add_argument('operation', choices=['add', 'sub', 'mul', 'div'], help='Operation to perform')
    parser.add_argument('num1', type=float, help='First number')
    parser.add_argument('num2', type=float, help='Second number')
    args = parser.parse_args()

    if args.operation == 'add':
        result = add(args.num1, args.num2)
    elif args.operation == 'sub':
        result = sub(args.num1, args.num2)
    elif args.operation == 'mul':
        result = mul(args.num1, args.num2)
    elif args.operation == 'div':
        result = div(args.num1, args.num2)
    else:
        raise ValueError("Invalid operation")

    print(f"Result: {result}")

if __name__ == "__main__":
    main()