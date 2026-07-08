import sys
import os
import base64

sys.path.append(os.path.join(os.path.abspath(os.path.dirname(__file__)), ".."))
from bilibili_api.utils.BytesReader import BytesReader

def decode_proto(data: bytes, indent=0) -> str:
    reader = BytesReader(data)
    out = []
    prefix = "  " * indent
    
    while not reader.has_end():
        try:
            # Read tag
            tag = reader.varint()
            field_number = tag >> 3
            wire_type = tag & 0x07
            
            if wire_type == 0:  # Varint
                val = reader.varint()
                out.append(f"{prefix}Field {field_number} (Varint): {val}")
            elif wire_type == 1:  # 64-bit
                val_bytes = reader.read(8)
                out.append(f"{prefix}Field {field_number} (64-bit): {val_bytes.hex()}")
            elif wire_type == 2:  # Length-delimited
                val_bytes = reader.bytes_string()
                # Try to parse recursively as a nested message
                try:
                    nested = decode_proto(val_bytes, indent + 1)
                    # If it parses successfully and contains fields, show as nested
                    if nested.strip():
                        out.append(f"{prefix}Field {field_number} (Message):")
                        out.append(nested)
                        continue
                except Exception:
                    pass
                
                # Try to decode as string
                try:
                    string_val = val_bytes.decode('utf-8')
                    # Ensure it's printable
                    if all(32 <= ord(c) < 127 or c in '\r\n\t' for c in string_val):
                        out.append(f"{prefix}Field {field_number} (String): {repr(string_val)}")
                        continue
                except Exception:
                    pass
                
                out.append(f"{prefix}Field {field_number} (Bytes): {val_bytes.hex()}")
            elif wire_type == 5:  # 32-bit
                val_bytes = reader.read(4)
                out.append(f"{prefix}Field {field_number} (32-bit): {val_bytes.hex()}")
            else:
                out.append(f"{prefix}Unknown wire type {wire_type} for field {field_number}")
                break
        except Exception as e:
            out.append(f"{prefix}Error parsing fields: {e}")
            break
            
    return "\n".join(out)

def analyze(input_str: str):
    # Try base64
    try:
        data = base64.b64decode(input_str)
    except Exception:
        # Try hex
        try:
            data = bytes.fromhex(input_str)
        except Exception:
            data = input_str.encode('utf-8')
            
    print("=== Protobuf Structure Analysis ===")
    print(decode_proto(data))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python proto_analyzer.py <base64_or_hex_string>")
    else:
        analyze(sys.argv[1])
