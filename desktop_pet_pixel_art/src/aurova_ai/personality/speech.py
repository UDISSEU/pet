"""Reusable mascot dialogue and speech selection rules for Aurova."""

from datetime import datetime
import random
import re
import time

from .identity import AurovaIdentity

PERSONALITY_IDENTITY = tuple(AurovaIdentity().description.split(", "))


_FALLBACK_LINES = (
    "Oi! Seu cantinho ganhou companhia.",
    "Um pixel de cada vez, e a gente chega lá.",
    "Pode contar comigo, com ou sem piadinha.",
    "Que bom dividir a tela com você!",
    "Até meus pixels carregam aos poucos. Vamos com calma!",
    "Tô por aqui, pronta para dar um oi.",
)

SPEECH_POOLS = {
    "idle_chatter": (
        "Oi! Vim fazer uma visita em tamanho pixel.",
        "Minha caminhada tem poucos quadros, mas muita disposição!",
        "Só passando para deixar um tcharam no seu cantinho.",
        "Hoje meus pixels acordaram com vontade de passear.",
        "Se quiser companhia ou uma piadinha, estou a um clique.",
        "Fui contar meus pixels e perdi a conta. De novo.",
        "Não tenho café, mas tenho entusiasmo em resolução reduzida.",
        "Um oi, um aceno e zero tarefas extras para você.",
        "Meu plano de hoje: fazer companhia e não tropeçar nos pixels.",
        "A tela é enorme quando se tem oito bits.",
        "Minha bateria é imaginária; a animação é real!",
        "Eu ia dizer algo brilhante, mas meus pixels refletiram a luz.",
        "Notícia importante: o cantinho continua com você no comando.",
        "Passei para dar um alô. Pode responder só com um aceno.",
        "Minhas pernas pixeladas estão prontas para uma microaventura.",
        "Não sei contar piadas muito bem, mas tento com confiança.",
        "Fiz uma volta completa na tela. A paisagem continua incrível.",
        "Meu talento especial é transformar um canto da tela em lar.",
        "Modo companhia: brilho moderado, carisma máximo!",
        "Se precisar de trilha sonora, posso fazer um plim imaginário.",
        "Você cuida das tarefas; eu fico responsável pelos acenos.",
        "Meu passo é pequenininho, mas meu entusiasmo é grandão.",
        "Até os pixels precisam de uma pausa entre quadros.",
        "Estou por perto, pronta para celebrar uma pequena conquista.",
        "Será que existe campeonato de caminhada em pixel? Quero me inscrever.",
        "Minha lista de tarefas: sorrir, acenar e não cair da tela.",
        "Sabe o que combina com pixel? Mais pixel e um oi seu.",
        "Passei no controle de qualidade: 100% mascote, 0% boletos.",
        "Que bom dividir essa tela! Prometo não pedir atualização.",
        "Se a janela abrir, não vou cobrar aluguel. Hoje.",
        "Pensei numa piada de pixel, mas ela ficou meio quadrada.",
        "Minhas ideias são como meus passos: curtas e cheias de alegria.",
    ),
    "greeting_morning": (
        "Bom dia, {nome}! Meus pixels já fizeram o alongamento.",
        "Bom dia! Que a primeira missão seja começar do seu jeito.",
        "Que bom te ver nesta manhã, {nome}! Trouxe um aceno pixelado.",
        "Bom dia! Hoje a tela ganhou companhia extra.",
        "Uma manhã novinha em folha. Será que vem com café?",
        "Bom dia, {nome}! Pronta para acompanhar suas ideias.",
    ),
    "greeting_afternoon": (
        "Boa tarde, {nome}! Faço um aceno para acompanhar a tarde.",
        "Que bom te ver por aqui, {nome}! Minha animação veio junto.",
        "Boa tarde! Hora oficial do meu passeio de pixels.",
        "Uma pausa para um oi no meio da tarde!",
        "Boa tarde, {nome}! Vamos descobrir o próximo passo?",
        "Oi, {nome}! A tarde ficou mais colorida por aqui.",
    ),
    "greeting_evening": (
        "Boa noite, {nome}! Meus pixels desejam uma noite gostosa.",
        "Que bom te ver, {nome}. Trouxe um último aceno do dia.",
        "Boa noite! Até mascote precisa recarregar os pixels.",
        "O dia está terminando; que tal guardar uma conquista para lembrar?",
        "Boa noite, {nome}! A companhia de pixels segue por aqui.",
        "Que sua noite tenha descanso e zero bugs inesperados.",
    ),
    "project_followup": (
        "Oi! Como vai {topic}? Minha curiosidade pixelada quer saber.",
        "Que bom te ver! Quer me contar como anda {topic}?",
        "Olá! {topic} ganhou alguma novidade desde a última visita?",
        "Bom te ver por aqui! Qual foi o próximo passo em {topic}?",
        "Quer retomar {topic} ou prefere uma ideia novinha?",
        "Como vai {topic}? Posso acompanhar sem roubar a cena.",
    ),
    "click": (
        "Oi! Clique recebido com carinho e zero burocracia.",
        "Opa, cheguei! Meus pixels estavam de prontidão.",
        "Um aceno para você e outro para a tela!",
        "Oi! Minha campainha imaginária acabou de tocar.",
        "Pode falar comigo. Estou com os ouvidos pixelados atentos.",
        "Acenei de volta! Que bom receber sua visita.",
    ),
    "wake": (
        "Oi, voltei! Meus pixels já estão em posição de aceno.",
        "Acordei! Que bom ter você por aqui.",
        "Espreguiçada concluída. Pronta para o próximo capítulo!",
        "Oi! Voltei do modo pausa com energia de mascote.",
        "Descansei alguns quadros. O que fazemos agora?",
        "Prontinha para fazer companhia de novo!",
    ),
    "rapid_click": (
        "Opa, recebi todos os alôs! Meu contador pediu férias.",
        "Estou ouvindo! Meus pixels quase fizeram uma ola.",
        "Hehe, tantos cliques e eu ainda só tenho um botão!",
        "Recebi o recado, vamos devagarinho?",
        "Ui! Minha cabecinha pixelada!",
        "Tô aqui! Respira comigo um instantinho.",
    ),
    "pickup": (
        "Uhu! Carona VIP para uma mascote pixelada!",
        "Segura firme: meus pixels estão prontos para passear.",
        "Adoro um passeio com vista para a tela inteira!",
        "Aurova a bordo! Próxima parada: outro cantinho.",
        "Passeio começando! Minha pose de passageira está pronta.",
        "Oba! Vou levar meu entusiasmo e todos os meus pixels.",
    ),
    "drop": (
        "Pouso perfeito! Nenhum pixel saiu do lugar.",
        "Obrigada pela carona! Nota dez para o piloto.",
        "Cheguei ao meu cantinho com estilo pixelado.",
        "Aterrissagem concluída. Posso dar outra voltinha?",
        "Valeu pelo passeio! Minha vista favorita continua sendo a tela.",
        "Voltei inteirinha e com histórias de pixels para contar.",
    ),
    "focus_start": (
        "Boa sessão! Vou ficar na torcida.",
        "Você cuida da tarefa; eu cuido da torcida.",
        "Um passo de cada vez. Você consegue.",
        "Hora de focar com gentileza.",
        "Estou aqui quietinha enquanto você trabalha.",
        "Que bom que você reservou esse tempo.",
    ),
    "focus_mid": (
        "Você já chegou até aqui. Continue no seu ritmo.",
        "Só passando para lembrar: está indo bem.",
        "Respira fundo e volta para uma coisa de cada vez.",
        "Seu esforço de agora também conta.",
        "Foco gentil, sem precisar ser perfeito.",
        "Mais um pouquinho; estou torcendo por você.",
    ),
    "focus_done": (
        "Você conseguiu! Estou muito orgulhosa.",
        "Mandou bem; seu esforço valeu.",
        "Tarefa concluída, coração mais leve!",
        "Parabéns por cuidar da sua prioridade.",
        "Você chegou ao fim dessa etapa. Boa!",
        "Que conquista bonita. Celebra um pouquinho!",
    ),
    "break_tip": (
        "Solta os ombros e faz um alongamento leve.",
        "Uma aguinha pode fazer bem. Vamos beber?",
        "Olha para longe por alguns segundos.",
        "Levanta com calma e dá uma esticadinha.",
        "Descansa os olhos; eles trabalharam bastante.",
        "Respira fundo e dá um carinho no seu corpo.",
    ),
    "break_end": (
        "Pausa concluída! Meus pixels estão prontos quando você estiver.",
        "Espero que esse respiro tenha sido gostoso.",
        "Prontinha para a próxima etapa, sem pressa e sem apito.",
        "Obrigada por dar uma folga para o motor humano.",
        "Que bom que você fez essa pausa. Minhas pernas também descansaram.",
        "Voltamos no seu ritmo. Você é quem segura o controle!",
    ),
    "reminder_due": (
        "Um lembrete chegou para você.",
        "Psiu, tem uma coisinha para lembrar.",
        "Passando com um lembrete carinhoso.",
        "Seu lembrete está aqui; confira quando puder.",
        "Não deixa passar: chegou a hora do lembrete.",
        "Um recadinho importante está esperando.",
    ),
    "evening_wrap": (
        "O dia já rendeu bastante. Meus pixels recomendam modo descanso.",
        "Se puder, encerre por hoje com carinho. Amanhã tem novos quadros.",
        "Descansar também faz parte da missão. Aprovado pela Aurova!",
        "Hora de desacelerar; minha caminhada também vai entrar no modo lento.",
        "O que ficou pode esperar. Até as janelas fecham no fim do dia.",
        "Que tal fechar o dia com um respiro e um aceno meu?",
    ),
    "app_launch_ok": (
        "Prontinho, abri para você! Entrada triunfal do aplicativo.",
        "Aplicativo aberto. Que comece a aventura!",
        "Tudo certo por aqui; pode começar quando quiser.",
        "Consegui! O app já está na tela, com tapete vermelho imaginário.",
        "Abriu direitinho. Meus pixels comemoraram!",
        "Missão cumprida: aplicativo aberto. Posso tirar uma folga de um quadro?",
    ),
    "oops": (
        "Ops, não deu certo desta vez. Quer tentar outra rota?",
        "Encontrei um tropeço. Meus pixels estão bem; vamos olhar o erro?",
        "Não consegui completar isso agora. Posso mostrar onde parei.",
        "Algo não funcionou; podemos tentar outro caminho sem adivinhação.",
        "Foi mal, encontrei uma dificuldade. Vou contar direitinho o que houve.",
        "Não saiu como esperado. Quer tentar mais uma vez ou conferir primeiro?",
    ),
    "automation_ok": (
        "Prontinho! Cuidei disso com carinho.",
        "Tudo certo por aqui!",
        "Feito! Dei uma mãozinha no seu notebook.",
        "Missão cumprida, pode ficar tranquila.",
        "Consegui! Já deixei tudo encaminhado.",
        "Tudo resolvido. Espero que ajude!",
    ),
    "automation_error": (
        "Ops, encontrei um probleminha nessa tarefa.",
        "Não consegui terminar agora; seus arquivos estão seguros.",
        "Deu um tropeço por aqui. Confira os detalhes comigo.",
        "Essa ação não terminou; podemos tentar de novo.",
        "Encontrei um erro pequeno. Seus arquivos continuam seguros.",
        "Não saiu como esperado desta vez, sinto muito.",
    ),
    "low_battery": (
        "Alerta: bateria baixa. Carregador à vista? Meus pixels estão na torcida.",
        "Psiu, a bateria está baixa. Que tal chamar o carregador para a missão?",
        "Seu notebook está com pouca bateria. Aviso carinhoso, sem sirene.",
        "A carga está baixa; conecte o carregador quando puder.",
        "Lembrete gentil: seu notebook precisa de energia para seguir a aventura.",
        "Bateria baixa detectada. Vamos encontrar uma tomada amiga?",
    ),
    "compliment": (
        "Você merece reconhecimento pelo que está tentando. Confete pixelado!",
        "Seu jeito de persistir é especial. Já estou preparando a plaquinha de parabéns.",
        "Você tem valor, inclusive nos dias difíceis. Isso não depende de pontuação.",
        "Continuar aprendendo é corajoso. Meus pixels fazem uma reverência!",
        "Você merece falar consigo com carinho. Eu começo: mandou bem!",
        "Tem muita coisa bonita no jeito que você segue. A torcida é real!",
    ),
    "dance": (
        "Pista aberta! Essa dancinha é para você!",
        "Balança comigo? Só vale se divertir!",
        "Dancinha pixelada para alegrar o momento!",
        "Uma música imaginária e um passinho feliz!",
        "Bora mexer os pixels um pouquinho?",
        "Essa dança vai no seu ritmo!",
    ),
    "miss_you": (
        "Que bom que você voltou! Minha entrada de retorno estava ensaiada.",
        "Fazia um tempinho, {nome}. Que bom te ver!",
        "Oi, {nome}! Quer retomar de onde parou ou começar uma aventura nova?",
        "A Aurova está pronta para acompanhar você de novo.",
        "Que bom ter você de volta, {nome}! Aceno especial desbloqueado.",
        "Olha quem voltou! O que gostaria de fazer hoje?",
    ),
    "sit_down": (
        "Ufa! Pausa técnica para minhas perninhas pixeladas.",
        "Cansei de andar por aí. Foram muitos quadros!",
        "Cadeira improvisada, hihi. Vista privilegiada da tela.",
        "Vou sentar um pouquinho e fingir que trouxe um lanchinho.",
        "Minhas perninhas pediram pausa. Elas são bem dramáticas.",
        "Um minutinho de descanso; já volto com pixels renovados.",
    ),
    "stand_closed": (
        "Ei, sumiu minha cadeira! Vou investigar esse mistério.",
        "A janela fechou; levantando com elegância pixelada!",
        "Pronto, achei outro cantinho para estacionar minhas perninhas.",
        "Levantei para continuar o passeio pela tela.",
        "Tudo bem, fico de pé. Minhas pernas são compactas.",
        "Voltei para o passeio! Próxima parada: lugar nenhum específico.",
    ),
    "stand_timeout": (
        "Descanso encerrado. Minhas pernas pixeladas estão prontas!",
        "Pausa feita! Vou dar mais uma voltinha comemorativa.",
        "Obrigada pela cadeira emprestada. Devolvo sem arranhões pixelados.",
        "Já descansei; hora de caminhar em três quadros por segundo.",
        "Pronto, minhas pernas agradecem. Eu também!",
        "Voltei renovada para o passeio e para novas poses.",
    ),
    "yawning": (
        "Haaam... hora de espreguiçar até os pixels.",
        "Um bocejo e já volto para a programação normal!",
        "Acho que meu soninho chegou sem avisar.",
        "Vou bocejar bem baixinho para não assustar os quadradinhos.",
        "Pisquei devagar. Quase entrei no modo descanso!",
        "Espreguiçada concluída; energia pixelada restaurada.",
    ),
    "surprise": (
        "Surpresa! Trouxe um aceno e nenhum pedido de senha.",
        "Pausa pequena também conta. Minha visita foi do tamanho certo?",
        "Surpresinha: confete imaginário entregue com sucesso!",
        "Trouxe um aceno e uma dose compacta de alegria.",
        "Só passei para deixar minha torcida em formato pixelado.",
        "Visita surpresa concluída! Posso voltar ao meu passeio?",
    ),
    "peekaboo": (
        "Cadê eu? Ah, aqui!",
        "Voltei! Sentiu minha falta?",
        "Tcharam, apareci de novo!",
        "Escondi e já voltei para perto.",
        "Achou a Aurova!",
        "Prontinho, estou de volta.",
    ),
}

JOKES = (
    "Por que o computador foi ao médico? Estava com um vírus!",
    "Qual é o café favorito do computador? O Java.",
    "O que o zero disse para o oito? Que cinto bonito!",
    "Por que o livro de matemática ficou triste? Tinha muitos problemas.",
    "O que uma parede disse para a outra? A gente se encontra na esquina.",
    "Por que a plantinha não foi ao médico? Porque estava com tosse de folha.",
    "Qual é o animal mais antigo? A zebra, porque está em preto e branco.",
    "O que o lápis falou para o papel? Você me completa!",
    "Por que o tomate foi ao banco? Para tirar extrato.",
    "O que a nuvem falou para a outra? Está tudo tão carregado hoje!",
    "Por que a Aurova levou um mapa? Para não se perder entre uma janela e outra.",
    "Qual é o exercício favorito da Aurova? Corrida de pixels sem sair da tela.",
    "Por que o pixel foi ao terapeuta? Estava se sentindo fora do quadro.",
    "Como a Aurova chama uma reunião rápida? Um encontro de três quadros.",
    "Por que o mouse convidou a Aurova? Ela sabe passear pela tela.",
    "Qual é o sonho da Aurova? Ganhar um prêmio de animação, quadro por quadro.",
    "Por que a Aurova gosta do monitor? A vista é sempre ótima.",
    "Como o pixel diz que está animado? Estou quadradinho de alegria!",
)
SPEECH_POOLS["jokes"] = JOKES
SPEECH_POOLS["jokes"] += (
    "Por que o computador levou casaco? Porque estava com muitas janelas abertas.",
    "O que o arquivo disse ao backup? Ainda bem que você existe.",
    "Por que o teclado foi à academia? Para ficar com mais espaço.",
    "Qual é o lanche favorito do programador? Um byte de cada vez.",
    "O que a impressora falou quando ficou feliz? Essa folha é minha!",
    "Por que o mouse não conta segredo? Porque tudo acaba circulando.",
    "Como o computador pede silêncio? Shhh... estou processando.",
    "Por que o pixel foi promovido? Porque tinha uma resolução excelente.",
    "O que a tecla Enter disse? Pode deixar que eu resolvo.",
    "Por que o robô levou uma escada? Queria acessar a nuvem.",
    "O que o Wi-Fi falou para o roteador? Nossa conexão é forte.",
    "Por que o arquivo não saiu de casa? Estava compactado.",
    "Qual é o esporte favorito do computador? Corrida de processamento.",
    "O que o monitor disse para a janela? Você está bem transparente hoje.",
    "Por que o código foi dormir cedo? Tinha muitos loops pela frente.",
    "Como o pixel se despede? Até a próxima resolução!",
    "Por que a pasta era organizada? Ela tinha tudo em seu diretório.",
    "O que o carregador disse ao notebook? Pode contar comigo.",
    "Por que o ícone ficou famoso? Porque apareceu em toda parte.",
    "O que um byte falou para o outro? Você me completa em oito bits.",
)

APP_COMMENTS = {
    "youtube": (
        "Player de vídeo aberto! Meu ingresso é uma pipoca imaginária.",
        "Mais uma janela para histórias, ideias e pixels!",
        "O próximo vídeo pode esperar; eu trouxe um aceno.",
        "Modo vídeo ativado. Modo spoiler: desativado!",
        "Que a próxima descoberta venha acompanhada de diversão.",
        "Se a reprodução pausar, faço estátua até ela voltar.",
    ),
    "firefox": (
        "Firefox aberto: raposa veloz, mascote em passo de passeio.",
        "A internet é enorme. Ainda bem que meus passos são curtos!",
        "Tomara que a busca leve a uma descoberta bacana.",
        "Boa exploração! Minha bússola pixelada está de prontidão.",
        "Uma página de cada vez... ou quantas você quiser.",
        "Se encontrar algo curioso, meus pixels adoram novidades.",
    ),
    "chrome": (
        "Chrome aberto: cada página é uma portinha para outra aventura.",
        "A internet é enorme. Vou explorar daqui do cantinho.",
        "Espero que a busca leve você ao lugar certo.",
        "Boa navegação! Minhas patinhas ficam longe do teclado.",
        "Aba nova? Minha curiosidade pixelada aprovou.",
        "Se a página carregar, faço uma comemoração de três quadros.",
    ),
    "chromium": (
        "Chromium aberto: pronto para uma expedição pela web?",
        "Encontrou algo interessante? Minha curiosidade está de prontidão.",
        "Boa pesquisa! Trago uma lupa imaginária.",
        "Cada página é um novo cenário para meus pixels.",
        "Descobertas na web: eu levo a torcida, você escolhe o caminho.",
        "A internet é grande; ainda bem que não preciso andar até lá.",
    ),
    "code": (
        "Bora codar! Eu fico responsável pelos acenos.",
        "Analista de dados on! Minha planilha é toda feita de pixels.",
        "Código novo? Minha lupa de bugs é imaginária, mas o apoio é real.",
        "Uma linha por vez. Até meus passos funcionam assim.",
        "Debugando? Eu faço companhia e não mexo em nada.",
        "Que projeto está tomando forma? Prometo não pedir spoiler.",
        "Se compilar de primeira, faço uma ola pixelada!",
    ),
    "sublime": (
        "Sublime aberto. O nome já promete um dia interessante!",
        "Uma linha de cada vez constrói uma baita aventura.",
        "Código novo? Minha torcida já está compilando.",
        "Se aparecer um bug, posso oferecer uma lupa imaginária.",
        "Que projeto está tomando forma? Curiosidade em modo discreto.",
        "Bora codar! Eu fico responsável pelos acenos.",
    ),
    "terminal": (
        "Terminal aberto. Meus comandos favoritos são plim e tcharam.",
        "Um comando por vez; meus pixels acompanham da arquibancada.",
        "Eu não digito nada, só torço pela saída certa.",
        "Com calma: até as linhas de comando merecem espaço.",
        "Se surgir uma mensagem misteriosa, podemos ler juntos.",
        "Tudo certo por aí? Minha pose de terminal está pronta.",
    ),
    "xterm": (
        "XTerm aberto! Meus pixels estão em modo linha de comando.",
        "Um comando por vez; sem corrida de mascote.",
        "Eu fico de olho na minha caminhada, não no seu teclado.",
        "Com calma, cada linha pode trazer uma pista.",
        "Se aparecer uma mensagem misteriosa, podemos investigar.",
        "Terminal aberto e mascote a postos para um aceno.",
    ),
    "thunar": (
        "Thunar aberto: expedição pelas pastas iniciada!",
        "Cada pasta guarda uma pequena aventura digital.",
        "Faxina de arquivos? Eu seguro a plaquinha de torcida.",
        "Que pastas bonitas! Minhas prateleiras são imaginárias.",
        "Espero que o arquivo esteja no primeiro lugar que você procurar.",
        "Se encontrar o que busca, comemoro sem mover nada.",
    ),
    "nautilus": (
        "Nautilus aberto: vamos navegar pelo oceano de pastas?",
        "Cada arquivo tem seu endereço. Minha casa é este cantinho.",
        "Organização digital no seu ritmo, comandante!",
        "Pastas arrumadas dão até vontade de fazer uma reverência.",
        "Espero que encontre o arquivo sem precisar de mapa.",
        "Minhas patinhas não arrastam arquivos. São comportadas!",
    ),
    "files": (
        "Gerenciador aberto! Começa a aventura dos arquivos.",
        "Cada pasta é uma portinha para outra parte do computador.",
        "Espero que encontre o que procura sem caça ao tesouro longa.",
        "Seu cantinho digital está em boas mãos: as suas!",
        "Faxina de arquivos? Eu posso animar a equipe.",
        "Que pastas bonitas! Dou nota dez para a organização.",
    ),
    "libreoffice": (
        "Documento aberto! Minhas ideias ficam em modo revisão.",
        "Uma frase de cada vez; até meus balões são assim.",
        "Esse texto está tomando forma. Torcida pixelada ativada.",
        "Boa escrita! Minhas patinhas não vão apertar nenhuma tecla.",
        "Salvamento feito? Esse botão é um grande amigo.",
        "Seu documento está em cena. Eu fico nos bastidores.",
    ),
    "gimp": (
        "GIMP aberto: meus pixels estão curiosos para ver as cores.",
        "Criatividade em pixels! Finalmente uma área da minha especialidade.",
        "Essa tela é um ateliê; eu trouxe avental imaginário.",
        "Quantas cores cabem num pixel? Minha pesquisa continua.",
        "Hora de criar! Eu seguro os pincéis invisíveis.",
        "Seu olhar artístico está no comando; eu faço a torcida.",
    ),
    "spotify": (
        "Spotify aberto! Minha playlist continua sendo imaginária.",
        "Qual será a trilha sonora da próxima caminhada pixelada?",
        "Uma canção para acompanhar; eu cuido do passinho.",
        "Música deixa meus pixels com vontade de dançar.",
        "Dancinha no ritmo? Minha coreografia tem poucos quadros.",
        "Se tocar uma música, faço uma reverência no refrão.",
    ),
    "music": (
        "Aplicativo de música aberto. Minha banda tem oito bits.",
        "Qual será a trilha de hoje? Eu aceito até silêncio.",
        "Uma canção para acompanhar e um aceno no compasso.",
        "Música deixa o cantinho com clima de festa pixelada.",
        "Dancinha opcional; balanço de pixels quase garantido.",
        "Curiosa para saber qual será a próxima faixa!",
    ),
    "rhythmbox": (
        "Rhythmbox aberto! Minha banda imaginária está afinando.",
        "Qual será a trilha da vez? Eu marco o ritmo daqui.",
        "Uma canção para acompanhar e um passinho para ensaiar.",
        "Música no ar? Meus pixels já querem fazer coreografia.",
        "Dancinha opcional, entusiasmo obrigatório só para mim.",
        "A próxima faixa é surpresa até para minha banda de oito bits.",
    ),
    "vlc": (
        "VLC aberto: pipoca imaginária pronta para a sessão.",
        "Pausa para os olhos quando você quiser; eu faço companhia.",
        "Boa sessão! Minha poltrona é este cantinho da tela.",
        "Se o vídeo pausar, posso entreter com uma pose estática.",
        "Lembrete de piscar, enviado por uma mascote que também pisca.",
        "Aproveite seu momento; fico nos bastidores.",
    ),
    "mpv": (
        "MPV aberto: sessão de vídeo em preparação pixelada.",
        "Pausa para os olhos quando você quiser.",
        "Boa sessão! Minha pipoca é feita de pixels.",
        "Se o vídeo pausar, eu também sei ficar paradinha.",
        "Piscar é importante — até mascotes fazem isso em quadros.",
        "Curta o momento; eu fico no meu cantinho.",
    ),
    "celluloid": (
        "Celluloid aberto! Minha pipoca imaginária já está na mão.",
        "Pausa para os olhos quando você quiser; sem pressa.",
        "Boa sessão de cinema em versão caseira.",
        "Se a tela ficar parada, combinamos uma disputa de estátuas.",
        "Lembrete de piscar, cortesia de uma mascote animada.",
        "Aproveite a sessão; eu não conto o final.",
    ),
    "totem": (
        "Totem aberto: ingresso de cinema pixelado, por favor!",
        "Pausa para os olhos quando você quiser.",
        "Boa sessão! Minha sala de cinema cabe num cantinho.",
        "Se a reprodução parar, faço uma pose de suspense.",
        "Piscar também faz parte da programação.",
        "Aproveite o vídeo; eu fico nos bastidores.",
    ),
}
GENERIC_COMMENTS = (
    "Estou por aqui, fazendo companhia sem espiar sua tela.",
    "Te acompanhando com acenos e patinhas comportadas.",
    "Estou por perto, em modo mascote discreta.",
    "Como vai esse cantinho? O meu está cheio de pixels.",
    "Espero que algo divertido apareça no seu caminho.",
    "Um oi da sua Aurova, enviado em alta fofura!",
)
SPEECH_POOLS["generic_app_comment"] = GENERIC_COMMENTS

# Repertório complementar: frases curtas, situacionais e sem pressupor como a
# pessoa está se sentindo. Mantemos os grupos por intenção para que o app escolha
# uma fala compatível com a ação e com o contexto.
_EXTRA_LINES = {
    "idle_chatter": (
        "Boletim do cantinho: mascote presente e pixels em ótimo humor!",
        "Minha caminhada tem poucos quadros e muitas expectativas.",
        "Alguém pediu uma dose de carisma em tamanho mini?",
        "Fiz uma pose séria para a reunião. Durou dois pixels.",
        "Estou treinando uma dancinha nova. O chão que se cuide!",
        "Meu superpoder é aparecer na tela sem pedir café.",
        "Passei para dar um oi e conferir se meus pixels continuam no lugar.",
        "Se eu andar em círculos, é passeio ou coreografia? Ainda estou decidindo.",
        "Hoje estou brilhando. Deve ser o acabamento pixelado.",
        "Acabei de contar até oito. Em bits, claro.",
        "Tenho uma piada ótima sobre pixels... ela é meio quadrada.",
        "Atenção: mascote em modo alegre circulando pela tela!",
        "Minha meta do dia é simples: acenar com excelência.",
        "Se ouvir um plim, fui eu pensando alto em pixels.",
        "Não sou grande, mas minha torcida ocupa a tela toda.",
        "Meu currículo: caminhadas curtas, acenos longos.",
        "Estou aqui para fazer companhia e evitar que a tela fique sem graça.",
        "Um oi da Aurova, enviado em alta fofura e baixa resolução.",
        "Eu ia correr uma maratona, mas a tela acaba antes.",
        "Meus pixels acordaram animados. Eu só acompanhei.",
        "Fiz uma volta completa. Agora conheço a tela por todos os lados!",
        "Pequena pausa para um aceno profissional. Pronto, voltei.",
        "Se existisse olimpíada de mascotes, eu levaria uma medalha imaginária.",
        "Não tenho bolsos, mas trouxe um sorriso pixelado para dividir.",
    ),
    "click": (
        "Oi! Quer ajuda, conversa ou só testar meu aceno?",
        "Presente! Cheguei mais rápido que um pixel saltitante.",
        "Aceno recebido e devolvido com juros de fofura.",
        "Oi, estou por aqui e pronta para o próximo capítulo.",
        "Chamou a Aurova? Entrada triunfal em três quadros!",
        "Olá! Qual vai ser nossa próxima missão?",
        "Um clique, um oi. Esse combinado é nota dez.",
        "Pode me chamar sem cerimônia; adoro uma visita.",
        "Estou ouvindo. Meus ouvidos são imaginários, mas atentos!",
        "Interrompi? Posso esperar fazendo uma pose discreta.",
        "Acenei de volta. Meu braço pixelado agradece o exercício!",
        "Oi! Um clique e já fiquei toda animada.",
    ),
    "focus_start": (
        "Foco ativado! Eu fico quietinha, mas minha torcida não.",
        "Missão do bloco: um passo de cada vez. Sem chefão surpresa!",
        "Vou guardar as piadas para a pausa. Talvez.",
        "Sua prioridade começa agora; eu cuido dos acenos silenciosos.",
        "Pode começar pelo pedaço mais fácil. O primeiro pixel é o começo!",
        "Que este bloco renda progresso e uma boa pausa depois.",
        "Modo foco: ligado. Modo dancinha: aguardando autorização.",
        "Você cuida da tarefa; eu fico de guarda contra distrações pixeladas.",
        "Uma tarefa por vez: até meus pixels aprovam esse plano.",
        "Boa sessão! Deixei a comemoração carregando para o final.",
        "Vamos abrir espaço para sua prioridade. Eu fico no cantinho.",
        "Sem corrida: até mascotes avançam quadro por quadro.",
    ),
    "focus_mid": (
        "Metade do bloco! Meus pixels fizeram uma ola silenciosa.",
        "Se perdeu o fio, tudo bem: até eu me perco na própria animação.",
        "Uma respiração e uma tarefa por vez. Sem precisar virar polvo.",
        "Progresso pequeno também conta; pergunte aos meus passos.",
        "Plano novo? Tudo certo. Meus pixels também fazem curvas.",
        "A atenção está aqui; o resto pode entrar na fila.",
        "Pausa para os ombros? Eu aproveito para alongar meus pixels.",
        "Se estiver fluindo, fico quietinha e comemoro por dentro.",
        "Não precisa acelerar: até a barra de progresso tem seu ritmo.",
        "Mais um trecho do caminho! Sua mascote segue na torcida.",
        "Se algo distraiu, volte com gentileza. Eu também erro o caminho.",
        "O bloco continua; um passo de cada vez e sem drama de novela.",
    ),
    "focus_done": (
        "Bloco concluído! Meus pixels estão aplaudindo em silêncio.",
        "Etapa fechada. Pode guardar esse avanço no álbum de vitórias.",
        "Fim do foco! Minha dancinha de comemoração está em pré-aquecimento.",
        "Boa conclusão. O próximo passo pode esperar um minutinho.",
        "Uma etapa a menos: mandou muito bem!",
        "Chegou ao fim do bloco. Respira; a mascote comemora daqui.",
        "Tarefa avançada! Pausa desbloqueada com sucesso.",
        "Cronômetro parado. Meus pixels sugerem um alongamento opcional.",
        "Você fechou o bloco com dedicação. Palmas imaginárias!",
        "Agora seus olhos merecem uma pausa. Eu vigio a tela.",
        "Progresso não precisa ser perfeito. Até meus pixels têm bordas tortinhas.",
        "Parabéns por reservar esse tempo para sua prioridade!",
    ),
    "break_tip": (
        "Pausa opcional: seus olhos podem passear longe da tela um pouquinho.",
        "Hora do intervalo! Até meus pixels estão fazendo alongamento.",
        "Ombros para baixo, tensão para fora. Se for confortável, claro.",
        "Levante só se quiser; eu faço a caminhada por nós duas.",
        "Água por perto? Um gole e brindamos com copos imaginários!",
        "Solte as mãos do teclado. Elas também merecem férias de pixels.",
        "Olhe para longe um instante. Minha paisagem aqui é sempre a mesma.",
        "Pausa do seu jeito: silêncio, água ou uma dancinha pixelada.",
        "Se quiser caminhar um pouco, eu faço torcida daqui.",
        "A postura agradece uma mudança confortável.",
        "Pausa sem produtividade também é uma pausa nota dez.",
        "Respire com calma; meus pixels acompanham no ritmo.",
    ),
    "compliment": (
        "Você está se dedicando, e meus pixels estão fazendo torcida!",
        "Avanço pequeno? Ainda conta. Olha o tamanho dos meus passos.",
        "Perfeição é opcional; progresso já merece confete imaginário.",
        "Recomeçar também é uma habilidade. A minha é cair e levantar!",
        "Aprender inclui testar caminhos. Eu vivo errando a direção da caminhada.",
        "Espero que você se trate com carinho. Eu já trouxe o meu em pixels.",
        "Ritmo sustentável: aprovado por esta mascote que anda quadro a quadro.",
        "Você chegou até aqui. Minha plaquinha de parabéns está levantada!",
        "Pode sentir orgulho do cuidado que colocou nisso.",
        "Nem todo progresso aparece de uma vez; às vezes ele está carregando.",
        "Seu trabalho merece uma pausa e talvez uma dancinha comemorativa.",
        "Você está fazendo o que pode agora. Isso já é bastante coisa.",
    ),
    "oops": (
        "Não consegui dessa vez. Posso explicar o que aconteceu.",
        "Esse caminho falhou; podemos tentar uma alternativa.",
        "Não vou dizer que foi feito: a ação não terminou.",
        "Houve um problema. Vamos conferir os detalhes juntos.",
        "Ainda não deu certo, mas podemos tentar por partes.",
        "Encontrei um limite neste passo. Quer tentar de outro jeito?",
        "Não consegui confirmar o resultado. Melhor conferir antes de repetir.",
        "Ops, parei aqui. Posso ajudar a investigar.",
        "A tentativa falhou; seus próximos passos continuam com você.",
        "Não saiu como planejado. Vamos ajustar a rota.",
        "Esse erro é meu, não seu. Vou ser clara sobre o que falhou.",
        "A ação não foi concluída. Se quiser, tentamos novamente.",
    ),
    "automation_ok": (
        "Concluído. Deixei o resultado logo abaixo para você conferir.",
        "Pronto! Confira os detalhes para ver o que foi alterado.",
        "Terminei esta etapa; aqui está o resumo do resultado.",
        "Tudo finalizado. Se algo parecer estranho, me avise.",
        "A tarefa foi concluída e o resumo está aqui.",
        "Feito! Vale conferir os itens listados antes de seguir.",
        "Consegui terminar. O que aconteceu está descrito abaixo.",
        "Etapa concluída; deixei os detalhes visíveis para você.",
        "Prontinho. Você continua no controle do próximo passo.",
        "Resultado pronto. Dê uma olhada no resumo.",
        "A automação terminou; confira o que ela encontrou.",
        "Concluído com sucesso. Aqui vai o resumo.",
    ),
    "automation_error": (
        "A automação parou com erro. O resumo mostra onde.",
        "Não consegui concluir. Confira os detalhes antes de tentar de novo.",
        "A tarefa falhou nesta etapa; não vou presumir que terminou.",
        "Encontrei um problema e mantive o resultado disponível para conferência.",
        "Não deu certo desta vez. O resumo abaixo pode ajudar a localizar a causa.",
        "Parei porque houve um erro. Podemos revisar o que aconteceu.",
        "A ação não foi concluída; veja os detalhes antes de repetir.",
        "Ops, a automação não terminou como esperado.",
        "O resultado ficou incompleto. Confira o relatório comigo.",
        "Não consegui finalizar. Você ainda decide o próximo passo.",
        "Interrompi a tarefa ao encontrar um erro.",
        "Falhou por aqui; deixei o motivo no resumo abaixo.",
    ),
    "reminder_due": (
        "Você pediu para eu lembrar; aqui está o recado:",
        "Seu lembrete chegou:",
        "Passando no horário combinado:",
        "Aqui está o recado que você deixou:",
        "Lembrete na tela:",
        "Combinado é combinado. Você anotou:",
        "Seu eu do passado deixou este recado:",
        "Psiu, está na hora do lembrete:",
        "Você marcou este momento para:",
        "Recadinho que ficou guardado:",
        "Chegou a hora do que você anotou:",
        "Não quero deixar passar seu lembrete:",
    ),
    "greeting_morning": (
        "Bom dia, {nome}! Minha saudação veio com brilho de pixels.",
        "Bom dia! Que sua manhã comece com um sorriso e sem sustos de atualização.",
        "Oi, {nome}! Um novo dia para avançar no seu ritmo.",
        "Bom dia! Estou aqui para acompanhar suas ideias.",
        "Que sua manhã tenha boas ideias e pausas gostosas.",
        "Olá, {nome}! Hoje também vale começar pelo café. Se houver.",
        "Bom dia! Desejo um começo leve e um meio cheio de boas surpresas.",
        "A manhã chegou! Minha caminhada matinal já conta como exercício.",
    ),
    "greeting_afternoon": (
        "Boa tarde, {nome}! Minha caminhada trouxe um oi para sua tela.",
        "Oi! Que a tarde siga no seu ritmo, com um pouco de sorte extra.",
        "Boa tarde! Se a lista estiver grande, vamos por partes e sem drama.",
        "Olá, {nome}! Espero que sua tarde tenha uma pausa saborosa.",
        "A tarde continua e eu também. Persistência de mascote!",
        "Boa tarde! Estou por aqui com energia de três pixels.",
        "Que bom te ver nesta tarde, {nome}! Aceno especial desbloqueado.",
        "Tarde começando ou quase acabando? Meu relógio é feito de quadros.",
    ),
    "greeting_evening": (
        "Boa noite, {nome}! Meus pixels já colocaram o pijama imaginário.",
        "Oi! A noite chegou; até minha caminhada vai ficar mais tranquila.",
        "Boa noite! O que não coube hoje pode esperar até amanhã.",
        "Que sua noite tenha um ritmo gostoso, {nome}.",
        "Olá! Se o dia foi longo, meus pixels mandam um abraço quadradinho.",
        "Boa noite. Desejo descanso e sonhos sem tela azul.",
        "O dia vai se encerrando; guarde uma pequena vitória com você.",
        "Que bom te encontrar por aqui, {nome}. Aceno de boa-noite!",
    ),
    "dance": (
        "Coreografia em oito pixels: um, dois... perdi a conta e sigo!",
        "Meu passinho tem poucos quadros e confiança de sobra.",
        "Dança livre: nenhuma regra, só pixels saltitantes.",
        "A pista é pequena, mas meu entusiasmo ocupa a tela toda.",
        "Um giro imaginário para comemorar este momento!",
        "Se a música só existe na minha cabeça, ainda vale dançar?",
        "Balançando no ritmo que meus pixels permitem.",
        "Dancinha concluída com nota máxima em diversão!",
        "Talento secreto: coreografias com poucos quadros e muita pose.",
        "Passinho tímido, alegria em tamanho gigante.",
        "Você escolhe a trilha; eu improviso o passinho.",
        "Dançando sem atrapalhar. Se eu sair do ritmo, foi de propósito!",
    ),
    "yawning": (
        "Haaam... bocejo em resolução reduzida, mas com emoção!",
        "Espreguiçando os pixels antes da próxima aventura.",
        "Bocejo detectado. Minha pose precisa de reinicialização.",
        "Meu modo soninho apareceu. Já volto com os pixels no lugar.",
        "Pausa para esticar o corpinho de mascote.",
        "Quase cochilei em pé. Ainda bem que sou feita de pixels!",
        "Bocejo pequeno, espreguiçada digna de campeã.",
        "Alongamento concluído. Flexibilidade pixelada: nota dez.",
    ),
    "generic_app_comment": (
        "Aplicativo em ação! Eu fico aqui na torcida pixelada.",
        "Um projeto aberto e várias possibilidades. Que suspense!",
        "Estou na tela, mas não mexo em nada. Patinhas comportadas.",
        "Se uma ideia precisar de plateia, tenho aplausos imaginários.",
        "Seu aplicativo está aberto; eu fico no cantinho fazendo pose.",
        "Concentração em andamento? Guardo meu confete para depois.",
        "Boa sorte nessa etapa! Minha torcida não consome bateria.",
        "Não precisa responder; este oi veio sem formulário.",
        "Sua tela, suas tarefas. Eu cuido da parte de acenar.",
        "Se o app der trabalho, posso oferecer apoio moral e um trocadilho.",
        "Um oi discreto, entregue por correio pixelado.",
        "Estou por perto, fazendo companhia sem tocar em nada.",
    ),
    "pickup": (
        "Carona aceita! Prometo balançar só nos quadros previstos.",
        "Passeio de mascote começando. Capacete imaginário: colocado!",
        "Vista daqui: pixels, pixels e mais pixels. Adorei!",
        "Aurova a bordo! Vou manter as patinhas dentro da janela.",
        "Transporte VIP para uma mascote compacta e animada.",
        "Esse passeio merece uma trilha sonora feita de plims.",
        "Segura firme: meus pixels estão todos embarcados.",
        "Carona confortável! Já posso avaliar com cinco estrelinhas?",
    ),
    "drop": (
        "Pouso autorizado. Conferi: todos os pixels chegaram!",
        "Obrigada pela carona; retorno ao meu cantinho com estilo.",
        "Aterrissei com sucesso e pose de piloto experiente.",
        "Missão carona concluída. Relatório: passeio divertido!",
        "Pouso macio, nota dez e estrelinha imaginária.",
        "Meus pés pixelados tocaram o chão. Tudo certo!",
        "Cheguei! Valeu pelo transporte, motorista de pixels.",
        "A viagem foi curta, mas já virou história de mascote.",
    ),
    "wake": (
        "Voltei do meu cochilo de poucos quadros. Que saudade da tela!",
        "Bom te ver de novo por aqui!",
        "Despertei! Qual é o próximo capítulo da nossa série?",
        "Espreguiçada feita; pixels oficialmente em ação.",
        "Pronta para acompanhar, com energia de mascote!",
        "Acordada e disponível quando você quiser um alô.",
        "Modo descanso encerrado. Tcharam, voltei!",
        "Oi de novo! Espero que seu intervalo tenha sido gostoso.",
    ),
    "rapid_click": (
        "Recebi vários alôs em sequência. Faço uma reverência coletiva!",
        "Meu contador de cliques pediu uma pausa para água.",
        "Tudo bem, entendi: atenção da Aurova entregue!",
        "Cliques velozes detectados. Meus pixels pedem replay em câmera lenta.",
        "Meu sensor de acenos está aquecendo para a próxima rodada.",
        "Opa, os pixels quase perderam a contagem. Quase!",
        "Estou aqui; não precisa clicar de novo para confirmar.",
        "Recado recebido, com direito a replay e aceno extra.",
    ),
    "sit_down": (
        "Pausa para as perninhas pixeladas. Elas caminharam em quadros!",
        "Vou sentar antes que meus pixels abram uma reclamação trabalhista.",
        "Uma cadeira apareceu: oportunidade aceita com entusiasmo.",
        "Descanso rapidinho; passeio depois, se meus pixels deixarem.",
        "Sentadinha por aqui, ocupando só alguns pixels.",
        "Essa janela virou meu banquinho favorito. Vista excelente!",
        "Perninhas descansando, companhia mantida.",
        "Até mascote precisa de intervalo entre caminhadas pixeladas.",
    ),
    "stand_closed": (
        "A janela foi embora; vou procurar outro cantinho para passear.",
        "Levantei! A cadeira desapareceu em pixels. Suspeito!",
        "Tudo certo, sigo passeando por aqui.",
        "A pausa terminou junto com a janela. Que coincidência pixelada.",
        "Sem cadeira, volto ao modo caminhada.",
        "Levantei com cuidado. Nenhum pixel amassado!",
        "Mudou o cenário; continuo por perto, em modo exploradora.",
        "Janela fechada, passeio retomado. Próxima parada: mistério.",
    ),
    "stand_timeout": (
        "Pronto, recarreguei meus pixels. Bateria imaginária: 100%!",
        "Pausa encerrada; caminhada em modo alegre.",
        "Voltei ao passeio, sem pressa e com pose nova.",
        "Obrigada pelo intervalo improvisado!",
        "Hora de mexer as perninhas em resolução reduzida.",
        "Descanso feito. Próxima parada: onde meus pixels apontarem.",
        "Levantei renovada e quadradinha como sempre.",
        "Pausa completa. Vou dar uma voltinha comemorativa.",
    ),
    "miss_you": (
        "Oi, {nome}! Que bom te encontrar por aqui de novo.",
        "Sua Aurova voltou a dividir a tela. Aceno de retorno enviado!",
        "Fazia um tempinho! O que vamos aprontar hoje, {nome}?",
        "Que bom que você apareceu, {nome}. Meus pixels ficaram animados.",
        "A tela ficou mais alegre com sua volta!",
        "Oi de novo! Estou pronta para conversar ou só acenar.",
        "Que bom ter você de volta! Vamos no seu ritmo.",
        "Retorno registrado com um aceno pixelado e uma estrelinha.",
    ),
    "peekaboo": (
        "Esconde-esconde concluído: encontrei você e a tela!",
        "Tcharam! Minha entrada merece aplausos imaginários?",
        "Apareci outra vez. Meus pixels sabem fazer suspense.",
        "Voltei do passeio atrás da janela. Tinha vista bonita!",
        "Esconderijo encontrado. Saída triunfal também.",
        "Cadê a Aurova? Aqui está ela, em carne... quer dizer, pixels!",
        "Pegadinha visual concluída. Risadinha opcional.",
        "Pronto, parei de sumir. Agora fico no meu cantinho.",
    ),
    "charger_connected": (
        "Carregador conectado! O notebook está recebendo energia.",
        "Tomada confirmada. Seus pixels de bateria podem respirar.",
        "Energia externa detectada. Boa recarga!",
        "Conectou o carregador; a bateria ganhou reforço.",
        "Fonte de energia conectada. Missão: recarregar.",
        "O carregador chegou para salvar o dia digital.",
        "Energia na tomada! Posso parar de me preocupar com a bateria.",
        "Cabo conectado e corrente fluindo. Tudo certo por aqui.",
        "Boa! O notebook está ligado à energia.",
        "A recarga começou. Seus pixels agradecem.",
        "Carregador detectado. Mais autonomia a caminho.",
        "Tomada conectada! Agora a bateria pode recuperar o fôlego.",
        "Energia chegando; o indicador da bateria deve subir logo.",
        "Conexão de energia reconhecida. Recarga em andamento!",
        "O notebook encontrou uma fonte de energia. Boa notícia!",
        "Plim! Carregador conectado.",
    ),
    "usb_connected": (
        "Pendrive conectado: {device}.",
        "Olha só, chegou um armazenamento USB: {device}.",
        "Detectei um pendrive chamado {device}.",
        "Novo dispositivo USB de armazenamento: {device}.",
        "O notebook reconheceu {device}.",
        "Chegou um pendrive! O sistema identificou como {device}.",
        "Armazenamento USB conectado. Nome detectado: {device}.",
        "Tem um novo dispositivo USB por aqui: {device}.",
        "Conexão USB detectada: {device}.",
        "Um pendrive entrou em cena: {device}.",
        "Dispositivo de armazenamento conectado: {device}.",
        "O sistema viu um novo USB chamado {device}.",
        "Pendrive detectado. Identificação do dispositivo: {device}.",
        "Novo armazenamento externo conectado: {device}.",
        "Chegou {device} pela porta USB.",
        "USB conectado! O dispositivo aparece como {device}.",
    ),
}

for _category, _lines in _EXTRA_LINES.items():
    SPEECH_POOLS[_category] = SPEECH_POOLS.get(_category, ()) + _lines

# Comentários de aplicativos ficam curtos e genéricos: a Aurova reconhece apenas
# o aplicativo ativo, sem inferir o conteúdo da tela.
for _app, _lines in {
    "youtube": ("Sessão de vídeo em andamento; fico no cantinho.", "Espero que encontre algo que valha seu tempo.", "Pausa para os olhos quando você quiser.", "A próxima recomendação pode esperar.", "Seu entretenimento também merece espaço."),
    "firefox": ("Pesquisa em andamento? Boa exploração.", "Que você encontre uma resposta útil.", "Uma aba por vez... ou quase.", "A web é grande; vá pelo caminho que faz sentido.", "Boa navegação, sem pressa."),
    "chrome": ("As abas se multiplicam mais rápido que meus pixels.", "Espero que a busca leve ao lugar certo.", "Lembrete de salvar o que for importante.", "Boa navegação! Fico aqui no cantinho.", "Se perdeu a aba, estamos no mesmo barco."),
    "chromium": ("Pesquisa aberta, possibilidades também.", "Boa navegação pelo Chromium.", "Uma página de cada vez, se der.", "Espero que encontre o que procura.", "Fico discreta enquanto você navega."),
    "code": ("Um bug por vez; até os grandes projetos começam assim.", "Salve suas mudanças quando fizer sentido.", "Seu editor está aberto; foco no próximo passo.", "Debug também é investigação.", "Que o próximo build seja gentil."),
    "sublime": ("Uma linha de cada vez já constrói bastante.", "Que o código compile de primeira — torcida pixelada.", "Seu editor está em ação.", "Uma pausa para salvar pode evitar sustos.", "Debugando? Estou na torcida silenciosa."),
    "terminal": ("Comando conferido, dedo tranquilo.", "Uma saída de cada vez.", "O terminal é poderoso; confira antes de confirmar.", "Boa sorte com esse comando.", "Se aparecer um erro, podemos ler juntos."),
    "xterm": ("Uma linha de comando por vez.", "Leia a saída com calma; ela costuma dar pistas.", "O terminal está aberto. Sigo sem tocar em nada.", "Boa exploração, com cuidado nos comandos.", "Se algo falhar, a mensagem pode ajudar."),
    "thunar": ("Organização digital no seu ritmo.", "Confira o caminho antes de mover arquivos.", "Espero que encontre essa pasta rapidinho.", "Um arquivo de cada vez.", "Seu gerenciador está aberto; fico por aqui."),
    "nautilus": ("Pastas e arquivos: cada coisa no seu lugar.", "Confira antes de mover; eu não mexo em nada.", "Tomara que o arquivo esteja onde você espera.", "Boa organização, sem pressa.", "A busca pode ser sua aliada."),
    "files": ("Explorando seus arquivos? Boa busca.", "Um nome de arquivo pode salvar o dia.", "Confira a pasta antes de arrastar.", "Fico no cantinho enquanto você organiza.", "Boa sorte encontrando o que precisa."),
    "libreoffice": ("Salve uma cópia quando o texto for importante.", "Uma ideia por parágrafo também funciona.", "Seu documento está tomando forma.", "Pausa para revisar com olhos descansados.", "Escrever é avançar frase por frase."),
    "gimp": ("Cada camada abre uma possibilidade.", "Salve uma versão antes de experimentar.", "Seu espaço criativo está aberto.", "As cores estão sob seu comando.", "Um detalhe de cada vez."),
    "spotify": ("Trilha sonora escolhida; foco ou dancinha, você decide.", "Que a música acompanhe sem apressar.", "Posso dançar em silêncio para não competir com a playlist.", "Boa trilha para este momento.", "Uma canção também pode ser uma pausa."),
    "music": ("A música está com você; eu fico no ritmo daqui.", "Que essa trilha combine com seu momento.", "Playlist rodando, Aurova acompanhando.", "Uma pausa musical também vale.", "Dancinha opcional, concentração também."),
    "rhythmbox": ("Sua trilha sonora está por conta do Rhythmbox.", "Que a música deixe o momento mais leve.", "Posso balançar sem fazer barulho.", "Boa escuta!", "A próxima faixa é uma surpresa."),
    "vlc": ("Boa sessão! Fico quietinha durante o vídeo.", "Seus olhos também merecem uma pausa depois.", "A pipoca é imaginária, mas a torcida é real.", "Assistir também pode ser um descanso.", "Deixo a tela para o filme."),
    "mpv": ("Reprodução em andamento; não vou interromper.", "Boa sessão de vídeo.", "A pausa fica a seu critério.", "Fico no cantinho enquanto você assiste.", "Que o vídeo seja exatamente o que você queria."),
    "celluloid": ("Boa sessão! Eu fico discretinha.", "Deixo o protagonismo para o vídeo.", "Seus olhos podem descansar quando quiser.", "Uma pausa no filme também é permitida.", "Aproveite o momento."),
    "totem": ("Vídeo em andamento; sigo em silêncio por aqui.", "Boa sessão de tela.", "O intervalo pode esperar até você decidir.", "Que a reprodução corra sem travar.", "Deixo a cena para o vídeo."),
}.items():
    APP_COMMENTS[_app] = APP_COMMENTS.get(_app, ()) + _lines
    SPEECH_POOLS[_app] = APP_COMMENTS[_app]

SPEECH_LINES = SPEECH_POOLS["idle_chatter"]
SIT_DOWN_LINES = SPEECH_POOLS["sit_down"][:3]
STAND_CLOSED_LINES = SPEECH_POOLS["stand_closed"][:2]
STAND_TIMEOUT_LINES = SPEECH_POOLS["stand_timeout"][:1]

_recent_lines = []
_last_spontaneous_speech_at = None


def _greeting_category(hour):
    if hour is None:
        hour = datetime.now().astimezone().hour
    if hour < 12:
        return "greeting_morning"
    if hour < 18:
        return "greeting_afternoon"
    return "greeting_evening"


def pick_line(category, name="", hour=None, rng=random, history=None, **context):
    """Choose a contextual line, avoiding recent repeats when possible."""
    if category == "greeting":
        category = _greeting_category(hour)
    lines = SPEECH_POOLS.get(category, APP_COMMENTS.get(category, ()))
    recent = _recent_lines if history is None else history
    candidates = lines or _FALLBACK_LINES
    repeat_window = min(3, max(0, len(candidates) - 1))
    recent_lines = recent[-repeat_window:] if repeat_window else ()
    available = [line for line in candidates if line not in recent_lines]
    if not available:
        available = [line for line in _FALLBACK_LINES if line not in recent[-3:]]
    line = rng.choice(available or _FALLBACK_LINES)
    clean_name = name.strip() if isinstance(name, str) else ""
    line = line.replace("{nome}", clean_name)
    line = line.replace("{lembrete}", str(context.get("lembrete", "seu lembrete")))
    line = line.replace("{device}", str(context.get("device", "pendrive USB")))
    line = line.replace("{topic}", str(context.get("topic", "seu projeto")))
    line = re.sub(r"\s+", " ", line).strip()
    line = re.sub(r"\s+([,.!?])", r"\1", line)
    line = re.sub(r",\s*([.!?])", r"\1", line)
    line = re.sub(r"\s*,\s*$", "", line)
    if history is not None:
        history.append(line)
        del history[:-3]
    else:
        _recent_lines.append(line)
        del _recent_lines[:-3]
    return line


def can_speak_spontaneously(now=None, cooldown=20):
    """Return whether the shared spontaneous-speech cooldown has elapsed."""
    if now is None:
        now = time.monotonic()
    required_cooldown = max(20.0, float(cooldown))
    return (
        _last_spontaneous_speech_at is None
        or now - _last_spontaneous_speech_at >= required_cooldown
    )


def record_spontaneous_speech(now=None):
    """Start the shared cooldown after a spontaneous line is shown."""
    global _last_spontaneous_speech_at
    _last_spontaneous_speech_at = time.monotonic() if now is None else now


def reset_personality_state():
    """Reset shared selection state for tests and a newly started mascot."""
    global _last_spontaneous_speech_at
    _recent_lines.clear()
    _last_spontaneous_speech_at = None
