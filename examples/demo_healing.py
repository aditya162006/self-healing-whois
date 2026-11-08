"""Offline integration demo; fake AI, in-memory state, no network calls."""
from self_healing_whois import healing
from self_healing_whois.parser import WhoisEntry


class DemoModel:
    def propose(self, text):
        return {'label': 'Registration valid until',
                'pattern': healing.pattern_for('Registration valid until'),
                'evidence': '2030-01-02'}


def main():
    text = 'Domain Name: EXAMPLE.COM\nRegistration valid until: 2030-01-02\n'
    healing.disable()
    entry = WhoisEntry.load('example.com', text)
    print('Before:', entry.expiration_date)
    client = healing.enable(provider=DemoModel(), repair_timeout=10)
    try:
        client.finish_lookup(entry)
        print('After: ', entry.expiration_date)
    finally:
        healing.disable()


if __name__ == '__main__':
    main()
