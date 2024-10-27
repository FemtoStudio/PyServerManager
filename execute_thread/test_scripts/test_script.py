import argparse
import json
import base64

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--encoded-args', help='Base64 encoded JSON arguments')
    args = parser.parse_args()

    if args.encoded_args:
        # Decode the base64 encoded arguments
        decoded_args = base64.b64decode(args.encoded_args).decode('utf-8')
        # Deserialize the JSON string into a dictionary
        data = json.loads(decoded_args)
        # Use 'data' as needed in your script
        print("Received arguments:", data)

if __name__ == '__main__':
    main()
