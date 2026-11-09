# Dodatkowe serwisy za Caddy Sophii

Caddy Sophii zajmuje porty 80/443 serwera i pobiera certyfikaty Let's Encrypt. Kolejne usługi
na tym samym VPS (np. `dashboard.giswgorach.pl`, `geokoder.giswgorach.pl`) dostają osobny plik
`<nazwa>.caddy` w tym katalogu. Caddy wczytuje tylko pliki `*.caddy`, więc ten README i przykład
`example.caddy.off` są pomijane.

## Usługa w innym projekcie Docker Compose

Dołącz kontener do wspólnej sieci `edge`, którą tworzy Sophia. Nie publikuj portów usługi.

```yaml
# docker-compose.yml usługi
services:
  dashboard:
    image: ...
    networks: [edge]
networks:
  edge:
    external: true
```

```caddy
# proxy/sites/dashboard.caddy
dashboard.giswgorach.pl {
	reverse_proxy dashboard:3000
}
```

## Usługa uruchomiona bezpośrednio na hoście (systemd)

Niech słucha na `0.0.0.0:<port>`, a w ufw ten port pozostaje zamknięty. Caddy łączy się z nią
przez `host.docker.internal`.

```caddy
geokoder.giswgorach.pl {
	reverse_proxy host.docker.internal:8081
}
```

Przeładowanie bez przerwy w działaniu:

```bash
docker compose exec proxy caddy reload --config /etc/caddy/Caddyfile
```

Usługi inne niż HTTP (np. RTMP 1935, RTSP 554/8554) nie przechodzą przez Caddy. Otwórz je
w zaporze: `sudo ufw allow 1935/tcp`.
