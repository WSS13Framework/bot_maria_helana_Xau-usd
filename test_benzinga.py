from benzinga_news import fetch_relevant_news


def main() -> None:
    try:
        all_news, filtered_news, config = fetch_relevant_news()
    except Exception as exc:  # pragma: no cover - operational output
        print(f"Erro ao consultar Benzinga: {exc}")
        return

    print(f"Env carregado: {config.get('env_path') or 'nenhum arquivo encontrado'}")
    print(f"Accept: {config['accept']}")
    print(f"Keywords ativas: {', '.join(config['keywords'])}")
    print(f"Notícias recebidas: {len(all_news)}")
    print(f"Notícias relevantes: {len(filtered_news)}")

    if not filtered_news:
        print("Nenhuma notícia passou pelo filtro de keywords.")
        return

    for item in filtered_news[: config["preview_limit"]]:
        title = item.get("title") or "sem título"
        created = item.get("created") or "sem data"
        matched = ", ".join(item.get("matched_keywords", []))

        print(f"  → {created} | {title}")
        print(f"    keywords: {matched}")

        if item.get("url"):
            print(f"    url: {item['url']}")


if __name__ == "__main__":
    main()
