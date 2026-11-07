"""Reusable, UI-independent personality lines and selection rules for Nova."""

from datetime import datetime
import random
import re
import time


PERSONALITY_IDENTITY = (
    "feliz e otimista", "alegre e divertida", "carinhosa e acolhedora",
    "proativa e curiosa", "atenciosa e paciente", "respeitosa e compreensiva",
)


_FALLBACK_LINES = (
    "Estou aqui com você.",
    "Um passinho de cada vez, tá?",
    "Pode contar comigo.",
    "Que bom dividir esse momento com você.",
    "Respira: não precisa resolver tudo de uma vez.",
    "Tô por aqui, no seu ritmo.",
)

SPEECH_POOLS = {
    "idle_chatter": (
        "Oi! Como está indo por aí?",
        "Passando para fazer companhia.",
        "Espero que seu dia esteja leve.",
        "Se precisar, é só me chamar.",
        "Estou aqui torcendo por você.",
        "Um carinho em forma de companhia.",
        "Já bebeu uma aguinha hoje?",
        "Vai no seu tempo; cada passo conta.",
        "Só um oi baixinho para alegrar seu cantinho.",
        "Estou por aqui, sem pressa e sem cobrança.",
        "Que bom compartilhar esse pedacinho do dia.",
        "Se quiser uma pausa, posso fazer companhia.",
    ),
    "greeting_morning": (
        "Bom dia, {nome}! Que seu começo seja gentil.",
        "Bom dia, {nome}! Um passo de cada vez.",
        "Que bom te ver nesta manhã, {nome}!",
        "Bom dia! Espero que você tenha descansado.",
        "Uma manhã novinha para começar com calma.",
        "Bom dia, {nome}! Estou aqui com você.",
    ),
    "greeting_afternoon": (
        "Boa tarde, {nome}! Como está seu ritmo?",
        "Que bom te ver por aqui, {nome}!",
        "Boa tarde! Espero que esteja tudo bem.",
        "Uma pausa carinhosa no meio da tarde.",
        "Boa tarde, {nome}! Vamos com calma.",
        "Oi, {nome}! Que a tarde seja leve.",
    ),
    "greeting_evening": (
        "Boa noite, {nome}! Espero que seu dia tenha sido bom.",
        "Que bom te ver, {nome}. Vamos desacelerar?",
        "Boa noite! Você merece um descanso tranquilo.",
        "O dia está terminando; pega leve com você.",
        "Boa noite, {nome}! Estou aqui pertinho.",
        "Que sua noite tenha um pouco de sossego.",
    ),
    "project_followup": (
        "Oi, que bom te ver! Como está {topic} desde a última vez?",
        "Que bom que voltou! Quer me contar como anda {topic}?",
        "Olá! Fiquei curiosa: como está indo {topic}?",
        "Bom te ver por aqui! O que avançou em {topic}?",
        "Oi! Quer retomar comigo o assunto de {topic}?",
        "Como está {topic}? Se quiser, posso acompanhar o próximo passo.",
    ),
    "click": (
        "Oi! Você me chamou?",
        "Opa, estou aqui!",
        "Um aceno só para você!",
        "Oi, que bom receber sua visita.",
        "Pode falar comigo quando quiser.",
        "Acenei de volta! Tudo bem por aí?",
    ),
    "wake": (
        "Oi, voltei! Espero que você tenha descansado também.",
        "Acordei! Que bom ter você por aqui.",
        "Um espreguiçar e já estou com você.",
        "Oi! Vamos voltar com calma?",
        "Descansei um pouquinho. Como posso acompanhar você?",
        "Prontinha para fazer companhia de novo.",
    ),
    "rapid_click": (
        "Calma, meu bem! Um clique de cada vez.",
        "Opa, estou ouvindo! Pode ir com calma.",
        "Hehe, assim eu fico tonta!",
        "Recebi o recado, vamos devagarinho?",
        "Ui! Minha cabecinha pixelada!",
        "Tô aqui! Respira comigo um instantinho.",
    ),
    "pickup": (
        "Eba, passeio no colo!",
        "Segurou firme? Lá vamos nós!",
        "Adoro uma carona com você.",
        "Estou segura aí, né?",
        "Passeio de Nova, que divertido!",
        "Pode me levar, vou com cuidado.",
    ),
    "drop": (
        "Pouso macio! Obrigada.",
        "Prontinho, voltei para o meu cantinho.",
        "Valeu pelo passeio!",
        "Cheguei inteirinha, obrigada pelo cuidado.",
        "Aterrissagem perfeita!",
        "Já estou de volta por aqui.",
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
        "Pausa feita! Quando quiser, seguimos.",
        "Espero que esse respiro tenha ajudado.",
        "Prontinha para a próxima etapa, sem pressa.",
        "Obrigada por cuidar de você um pouquinho.",
        "Que bom que você fez essa pausa.",
        "Voltamos no seu ritmo. Você decide.",
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
        "O dia já rendeu bastante. Pode descansar.",
        "Se puder, encerra por hoje com carinho.",
        "Seu descanso também faz parte do caminho.",
        "Hora de desacelerar e cuidar de você.",
        "O que ficou pode esperar um pouquinho.",
        "Que tal fechar o dia com uma respiração tranquila?",
    ),
    "app_launch_ok": (
        "Prontinho, abri para você!",
        "Aplicativo aberto. Bom proveito!",
        "Tudo certo por aqui; pode começar.",
        "Consegui! Já deixei o app prontinho.",
        "Abriu direitinho. Vamos nessa?",
        "Missão cumprida, o app está aberto!",
    ),
    "oops": (
        "Ops, não deu certo desta vez. Quer tentar de novo?",
        "Encontrei um tropeço, mas estou aqui com você.",
        "Não consegui completar isso agora. Vamos com calma?",
        "Algo não funcionou; podemos tentar outro caminho.",
        "Foi mal, encontrei uma dificuldade por aqui.",
        "Não saiu como esperado. Quer tentar mais uma vez?",
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
        "Sua bateria está baixinha. Se puder, conecte o carregador.",
        "Psiu, a bateria está chegando ao fim. Que tal carregar o notebook?",
        "Seu notebook está com pouca bateria. Estou avisando com carinho.",
        "A bateria está em um nível baixo; procure o carregador quando puder.",
        "Um lembrete gentil: sua bateria precisa de energia.",
        "A carga está quase acabando. Vamos deixar o notebook respirar na tomada?",
    ),
    "compliment": (
        "Você merece reconhecimento pelo que está tentando.",
        "Seu jeito de persistir é muito especial.",
        "Você tem valor, inclusive nos dias difíceis.",
        "Gosto da sua coragem de continuar aprendendo.",
        "Você merece falar consigo com carinho.",
        "Tem muita coisa bonita no jeito que você segue.",
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
        "Que saudade! Fico feliz que você voltou.",
        "Fazia um tempinho, {nome}. Que bom te ver!",
        "Senti falta da sua companhia por aqui.",
        "Olha quem voltou! Meu dia ficou mais alegre.",
        "Que bom ter você de volta, {nome}!",
        "A casa ficou mais feliz com sua visita.",
    ),
    "sit_down": (
        "Ufa... só um descansinho.",
        "Cansei de andar por aí.",
        "Cadeira improvisada, hihi.",
        "Vou sentar um pouquinho, tudo bem?",
        "Minhas perninhas pediram uma pausa.",
        "Um minutinho de descanso por aqui.",
    ),
    "stand_closed": (
        "Ei, sumiu minha cadeira!",
        "A janela fechou, levantando!",
        "Pronto, achei outro cantinho.",
        "Levantei para continuar por aqui.",
        "Tudo bem, fico de pé mais um pouco.",
        "Voltei para o passeio!",
    ),
    "stand_timeout": (
        "Descanso acabou, vamo lá de novo.",
        "Pausa feita! Vou dar mais uma voltinha.",
        "Obrigada pela cadeira emprestada.",
        "Já descansei; hora de caminhar.",
        "Pronto, minhas pernas agradecem!",
        "Voltei renovada para o passeio.",
    ),
    "yawning": (
        "Haaam... hora de espreguiçar.",
        "Um bocejo e já volto!",
        "Acho que meu soninho está chegando.",
        "Vou bocejar bem baixinho.",
        "Pisquei devagar, quase cochilei.",
        "Uma espreguiçada para renovar as energias.",
    ),
    "surprise": (
        "Passei só para deixar um oi para você!",
        "Uma pausa pequena também conta.",
        "Surpresinha: você está indo muito bem!",
        "Trouxe um aceno e um pouquinho de companhia.",
        "Só queria lembrar que estou torcendo por você.",
        "Uma visita surpresa para alegrar o cantinho!",
    ),
    "peekaboo": (
        "Cadê eu? Ah, aqui!",
        "Voltei! Sentiu minha falta?",
        "Tcharam, apareci de novo!",
        "Escondi e já voltei para perto.",
        "Achou a Nova!",
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
        "Rindo do vídeo ou é sério isso?",
        "Mais um vídeo pra 'só um rapidinho', né?",
        "O algoritmo te pegou de novo.",
        "Assistindo ou trabalhando? 👀",
        "Esse vídeo parece interessante!",
        "Pausa para um vídeo também vale.",
    ),
    "firefox": ("Navegando por aí?", "Achou algo legal?", "A internet está cheia de caminhos.", "Muitas abas abertas?", "Boa pesquisa!", "Descobrindo novidades?"),
    "chrome": ("Navegando por aí?", "Muitas abas, hein?", "Encontrou o que procurava?", "Boa pesquisa!", "A internet está cheia de caminhos.", "Só mais uma aba?"),
    "chromium": ("Navegando por aí?", "Encontrou algo interessante?", "Boa pesquisa!", "Muitas abas abertas?", "Descobrindo novidades?", "A internet está cheia de caminhos."),
    "code": ("Bora codar!", "Código novo?", "Analista de dados on!", "Uma linha por vez.", "Debugando com carinho?", "Que projeto está tomando forma?"),
    "sublime": ("Editando código?", "Uma linha por vez.", "Código novo?", "Debugando com carinho?", "Que projeto está tomando forma?", "Bora codar!"),
    "terminal": ("Modo terminal ativado.", "Linha de comando é vida!", "Um comando por vez.", "O terminal está sob controle?", "Com calma e um comando de cada vez.", "Tudo certo nesse terminal?"),
    "xterm": ("Modo terminal ativado.", "Um comando por vez.", "O terminal está sob controle?", "Linha de comando é vida!", "Com calma e um comando de cada vez.", "Tudo certo nesse terminal?"),
    "thunar": ("Organizando arquivos?", "Tudo no seu lugar?", "Faxina digital em andamento?", "Que pastas bonitas!", "Seu cantinho está organizado.", "Encontrou o arquivo?"),
    "nautilus": ("Organizando arquivos?", "Tudo no seu lugar?", "Faxina digital em andamento?", "Que pastas bonitas!", "Seu cantinho está organizado.", "Encontrou o arquivo?"),
    "files": ("Vendo seus arquivos?", "Tudo no seu lugar?", "Encontrou o que procurava?", "Seu cantinho está organizado.", "Faxina digital em andamento?", "Que pastas bonitas!"),
    "libreoffice": ("Trabalhando em documento?", "Uma frase de cada vez.", "Esse texto está tomando forma.", "Boa escrita!", "Pausa para salvar?", "Seu trabalho está avançando."),
    "gimp": ("Editando imagem, que bonito!", "Criatividade em pixels!", "Essa arte está tomando forma.", "Que cores lindas!", "Hora de criar!", "Seu olhar artístico está on."),
    "spotify": ("Boa música?", "Qual será a trilha de hoje?", "Uma canção para acompanhar.", "Música deixa o dia mais leve.", "Dancinha no ritmo?", "Curte essa música!"),
    "music": ("Boa música?", "Qual será a trilha de hoje?", "Uma canção para acompanhar.", "Música deixa o dia mais leve.", "Dancinha no ritmo?", "Curte essa música!"),
    "rhythmbox": ("Boa música?", "Qual será a trilha de hoje?", "Uma canção para acompanhar.", "Música deixa o dia mais leve.", "Dancinha no ritmo?", "Curte essa música!"),
    "vlc": ("Curtindo um vídeo?", "Pausa para os olhos também vale.", "Boa sessão de cinema!", "Esse vídeo parece interessante.", "Não esquece de piscar!", "Aproveitando seu momento?"),
    "mpv": ("Curtindo um vídeo?", "Pausa para os olhos também vale.", "Boa sessão de cinema!", "Esse vídeo parece interessante.", "Não esquece de piscar!", "Aproveitando seu momento?"),
    "celluloid": ("Curtindo um vídeo?", "Pausa para os olhos também vale.", "Boa sessão de cinema!", "Esse vídeo parece interessante.", "Não esquece de piscar!", "Aproveitando seu momento?"),
    "totem": ("Curtindo um vídeo?", "Pausa para os olhos também vale.", "Boa sessão de cinema!", "Esse vídeo parece interessante.", "Não esquece de piscar!", "Aproveitando seu momento?"),
}
GENERIC_COMMENTS = (
    "Vendo o que você está fazendo.",
    "Te acompanhando por aqui.",
    "Estou por perto.",
    "Como vai esse cantinho?",
    "Espero que esteja tudo bem.",
    "Um oi da sua Nova!",
)
SPEECH_POOLS["generic_app_comment"] = GENERIC_COMMENTS

# Repertório complementar: frases curtas, situacionais e sem pressupor como a
# pessoa está se sentindo. Mantemos os grupos por intenção para que o app escolha
# uma fala compatível com a ação e com o contexto.
_EXTRA_LINES = {
    "idle_chatter": (
        "Estou de plantão no cantinho, sem pressa.",
        "Seu espaço digital ganhou uma companhia de pixels.",
        "Se hoje estiver corrido, vamos por partes.",
        "Uma pausa entre tarefas também faz parte do trabalho.",
        "Passando em modo silencioso para desejar uma boa jornada.",
        "Posso ficar aqui quietinha enquanto você cuida das coisas.",
        "Que seu próximo passo seja possível, não perfeito.",
        "Estou por perto caso uma ideia precise de companhia.",
        "Intervalo de pixels: tudo certo por aqui.",
        "Sem cobrança da minha parte. Só companhia mesmo.",
        "O ritmo é seu; eu acompanho daqui.",
        "Às vezes, começar pequeno já destrava o dia.",
        "Que bom dividir a tela com você.",
        "Se quiser conversar, pode me chamar quando quiser.",
        "Um minuto de cada vez também leva longe.",
        "Deixei uma torcida discreta aqui no cantinho.",
        "Não precisa responder; só vim deixar um oi.",
        "Tudo bem fazer uma coisa por vez.",
        "Estou aqui para ajudar quando você pedir.",
        "Modo companhia ativado: presença leve, sem alarde.",
        "Seu próximo passo não precisa resolver tudo.",
        "Uma janela de cada vez, uma tarefa de cada vez.",
        "Que a tecnologia coopere com você hoje.",
        "Se algo emperrar, a gente pensa em outro caminho.",
    ),
    "click": (
        "Oi! Quer alguma coisa ou foi só um alô?",
        "Presente! Pode falar comigo.",
        "Aceno recebido e devolvido.",
        "Oi, estou por aqui.",
        "Chamou a Nova? Cheguei!",
        "Olá! Como posso ajudar agora?",
        "Um clique, um oi. Gostei desse combinado.",
        "Oi! Fico aqui à disposição.",
        "Pode me chamar sem cerimônia.",
        "Estou ouvindo. O que você precisa?",
        "Oi! Interrompo alguma coisa? Posso esperar.",
        "Acenei de volta. Tudo certo?",
    ),
    "focus_start": (
        "Combinado: foco na sua prioridade e eu fico discreta.",
        "A sessão começou. Quebre a tarefa em passos pequenos.",
        "Vou acompanhar sem puxar conversa durante o foco.",
        "Seu objetivo está anotado; seguimos uma etapa por vez.",
        "Pode começar pelo pedaço mais simples.",
        "Que este bloco seja produtivo e gentil com você.",
        "Foco ligado. Eu guardo as piadas para a pausa.",
        "Estou aqui, mas deixo a concentração com você.",
        "Uma tarefa por vez já é um ótimo plano.",
        "Boa sessão. A pausa também já está no nosso plano.",
        "Vamos dar espaço para essa prioridade.",
        "Seu tempo de foco começa agora; sem pressa de perfeição.",
    ),
    "focus_mid": (
        "Chegou ao meio do bloco. Continue no seu compasso.",
        "Se perdeu o fio, retome pelo próximo passo visível.",
        "Uma respiração e uma tarefa por vez.",
        "O progresso pode ser pequeno e ainda assim contar.",
        "Está tudo bem ajustar o plano e seguir.",
        "Sua atenção está nesse momento; o resto pode esperar.",
        "Pausa para os ombros? Depois você decide se continua.",
        "Se estiver fluindo, sigo quietinha por aqui.",
        "Não precisa acelerar para fazer progresso.",
        "Mais um trecho do caminho. Você escolhe o ritmo.",
        "Se algo distraiu você, volte sem se culpar.",
        "O bloco ainda está acontecendo. Um passo de cada vez.",
    ),
    "focus_done": (
        "Bloco concluído. Seu tempo e sua atenção foram investidos.",
        "Você fechou esta etapa. Reconheça esse avanço.",
        "Fim do foco! Agora cabe uma pausa de verdade.",
        "Boa conclusão. O que vem depois pode esperar um instante.",
        "Uma etapa a menos na lista. Mandou bem.",
        "Você chegou ao fim do bloco; respire antes do próximo.",
        "Tarefa avançada! Sua pausa está merecida.",
        "O cronômetro parou. Solte a tensão se puder.",
        "Fechou o bloco com dedicação. Muito bom.",
        "Agora é hora de descansar os olhos e a cabeça.",
        "O resultado pode ser imperfeito e ainda ser progresso.",
        "Parabéns por reservar esse tempo para sua prioridade.",
    ),
    "break_tip": (
        "Se puder, afaste os olhos da tela por um instante.",
        "Uma pausa curta pode ajudar a renovar a atenção.",
        "Dê uma chance aos ombros: abaixe e relaxe devagar.",
        "Levante só se isso for confortável para você.",
        "Água por perto? Um gole já é suficiente.",
        "Solte as mãos do teclado e mexa os dedos um pouquinho.",
        "Olhe para um ponto distante, sem forçar a vista.",
        "Aproveite a pausa do seu jeito: silêncio também vale.",
        "Se quiser, caminhe um pouco antes de voltar.",
        "Descanse a postura e escolha quando retomar.",
        "Uma pausa não precisa ser produtiva para ser útil.",
        "Dê alguns segundos para a respiração desacelerar.",
    ),
    "compliment": (
        "Você está se dedicando, e isso merece ser reconhecido.",
        "Um avanço pequeno continua sendo um avanço.",
        "Seu esforço não precisa ser perfeito para ter valor.",
        "Você pode recomeçar quantas vezes precisar.",
        "Aprender também inclui testar caminhos que não funcionam.",
        "Espero que você se trate com a mesma gentileza que oferece.",
        "O ritmo sustentável vale mais que correr até cansar.",
        "Você chegou até aqui; isso já faz parte da história.",
        "Pode sentir orgulho do cuidado que colocou nisso.",
        "Nem todo progresso aparece de uma vez.",
        "Seu trabalho merece uma pausa para respirar.",
        "Você está fazendo o que pode com o tempo de agora.",
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
        "Bom dia, {nome}! Que o começo do dia seja possível e tranquilo.",
        "Bom dia! Espero que sua manhã tenha espaço para respirar.",
        "Oi, {nome}! Começamos sem pressa, uma coisa por vez.",
        "Bom dia! Estou por aqui para acompanhar seu ritmo.",
        "Que sua manhã tenha boas ideias e pausas suficientes.",
        "Olá, {nome}! Um novo dia, sem obrigação de resolver tudo já.",
        "Bom dia! Desejo um começo gentil para você.",
        "A manhã chegou. Vamos descobrir o que cabe nela?",
    ),
    "greeting_afternoon": (
        "Boa tarde, {nome}! Como está sendo seu dia até aqui?",
        "Oi! Que a tarde siga no ritmo que funciona para você.",
        "Boa tarde! Se o dia estiver cheio, vamos por partes.",
        "Olá, {nome}! Espero que sua tarde tenha uma pausa boa.",
        "Uma nova metade do dia para continuar do seu jeito.",
        "Boa tarde! Estou por aqui, sem pressa.",
        "Que bom te ver por aqui nesta tarde, {nome}.",
        "Tarde começando ou quase acabando? Eu acompanho daqui.",
    ),
    "greeting_evening": (
        "Boa noite, {nome}. Espero que você encontre um pouco de sossego.",
        "Oi! A noite também pode ser um bom momento para desacelerar.",
        "Boa noite! O que não coube hoje pode esperar.",
        "Que sua noite tenha um ritmo mais gentil, {nome}.",
        "Olá! Se o dia foi longo, agora cabe respirar.",
        "Boa noite. Desejo um descanso sem pressa.",
        "O dia vai se encerrando; cuide de você no seu tempo.",
        "Que bom te encontrar por aqui, {nome}. Boa noite!",
    ),
    "dance": (
        "Coreografia em oito pixels: um, dois... já esqueci, mas sigo!",
        "Meu passinho tem poucos quadros e muita confiança.",
        "Dança livre: nenhuma regra, só alguns pixels felizes.",
        "A pista é pequena, mas o entusiasmo cabe inteiro.",
        "Um giro imaginário para comemorar este instante.",
        "Se a música está só na minha cabeça, ainda vale dançar?",
        "Balançando no ritmo que os meus pixels permitem.",
        "Dancinha concluída com nota máxima em diversão.",
        "Meu talento secreto: coreografias com poucos quadros.",
        "Passinho tímido, alegria em tamanho grande.",
        "A trilha sonora fica por sua conta; eu cuido do passinho.",
        "Dançando sem atrapalhar o seu ritmo.",
    ),
    "yawning": (
        "Haaam... foi um bocejo em resolução reduzida.",
        "Espreguiçando os pixels antes de continuar.",
        "Bocejo detectado. Vou recuperar minha pose.",
        "Meu modo soninho apareceu por alguns segundos.",
        "Uma pausa para esticar o corpo inteiro.",
        "Quase cochilei em pé. Já voltei!",
        "Bocejo pequeno, espreguiçada caprichada.",
        "Só alongando os pixels. Tudo pronto por aqui.",
    ),
    "generic_app_comment": (
        "Como está indo essa tarefa? Posso ficar quieta também.",
        "Um projeto aberto e muitas possibilidades.",
        "Estou acompanhando a tela sem mexer em nada.",
        "Se precisar de ajuda com uma ideia, me chame.",
        "Seu aplicativo está aberto; sigo aqui no cantinho.",
        "Concentração em andamento? Posso não interromper.",
        "Boa sorte com essa etapa!",
        "Tudo certo por aí? Não precisa responder agora.",
        "Sua tela, suas tarefas; eu só faço companhia.",
        "Se o app der trabalho, podemos pensar em alternativas.",
        "Um oi discreto enquanto você trabalha.",
        "Estou por perto enquanto você usa esse aplicativo.",
    ),
    "pickup": (
        "Carona aceita! Prometo não balançar muito.", "Passeio de mascote começando agora.",
        "Vista daqui: pixels, pixels por todo lado.", "Estou segura? Então vamos passear.",
        "Transporte VIP para uma mascote minúscula.", "Esse passeio merece uma trilha sonora imaginária.",
        "Segura firme que eu levo meus pixels comigo.", "Carona confortável, obrigada!",
    ),
    "drop": (
        "Pouso autorizado. Nenhum pixel ficou para trás.", "Obrigada por me devolver ao meu cantinho.",
        "Aterrissei com sucesso e estilo.", "Voltei ao chão; missão de carona concluída.",
        "Pouso macio, nota dez.", "Pronto, meus pés pixelados estão no chão.",
        "Cheguei! Valeu pelo transporte.", "A viagem foi curta, mas rendeu história.",
    ),
    "wake": (
        "Voltei do meu cochilo de poucos quadros.", "Bom te ver de novo na tela.",
        "Despertei! Qual é o próximo capítulo?", "Um espreguiçar e meus pixels entram em ação.",
        "Pronta para acompanhar, no seu ritmo.", "Acordada e disponível quando você precisar.",
        "Meu modo descanso terminou; olá outra vez!", "Oi de novo! Espero que seu intervalo tenha sido bom.",
    ),
    "rapid_click": (
        "Recebi vários alôs em sequência!", "Meu contador de cliques está trabalhando horas extras.",
        "Tudo bem, entendi: você quer minha atenção.", "Cliques velozes detectados. Continuo aqui!",
        "Meu sensor de acenos pediu uma pausa.", "Opa, os pixels quase perderam a contagem.",
        "Estou aqui; não precisa clicar mais para confirmar.", "Recado recebido, com direito a replay.",
    ),
    "sit_down": (
        "Pausa para as perninhas pixeladas.", "Vou sentar antes que meus pixels peçam demissão.",
        "Uma cadeira apareceu: oportunidade aceita.", "Descanso rápido, passeio depois.",
        "Sentadinha por aqui, sem ocupar muito espaço.", "Essa janela virou meu banquinho favorito.",
        "Pernas descansando, companhia mantida.", "Até mascote precisa de intervalo entre caminhadas.",
    ),
    "stand_closed": (
        "A janela foi embora; vou procurar outro lugar.", "Levantei! A cadeira desapareceu em pixels.",
        "Tudo certo, sigo passeando por aqui.", "A pausa terminou junto com a janela.",
        "Sem cadeira, volto para o modo caminhada.", "Levantei com cuidado. Nenhum pixel amassado.",
        "Mudou o cenário; continuo por perto.", "Janela fechada, passeio retomado.",
    ),
    "stand_timeout": (
        "Pronto, já recarreguei meus pixels.", "Pausa encerrada; caminhada em modo econômico.",
        "Voltei ao passeio, sem pressa.", "Obrigada pelo intervalo improvisado.",
        "Hora de mexer as perninhas outra vez.", "Descanso feito. Próxima parada: lugar nenhum específico.",
        "Levantei renovada em resolução pixelada.", "Pausa completa. Vou dar uma voltinha.",
    ),
    "miss_you": (
        "Oi, {nome}! Que bom te encontrar por aqui de novo.", "Sua Nova voltou a dividir a tela com você.",
        "Fazia um tempinho! Como posso acompanhar você hoje?", "Que bom que você apareceu, {nome}.",
        "A tela ficou mais movimentada com sua volta.", "Oi de novo! Estou disponível quando você quiser.",
        "Bem-vinda de volta, {nome}! Vamos no seu ritmo.", "Retorno registrado com um aceno pixelado.",
    ),
    "peekaboo": (
        "Esconde-esconde concluído: encontrei a tela de novo.", "Tcharam! Minha entrada foi discreta?",
        "Apareci outra vez, sem deixar rastros de pixels.", "Voltei do meu passeio atrás da janela.",
        "Esconderijo encontrado. Saída também.", "Cadê a Nova? Aqui está ela.",
        "Pegadinha visual concluída com sucesso.", "Pronto, parei de brincar de sumir.",
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

# Comentários de aplicativos ficam curtos e genéricos: a Nova reconhece apenas
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
    "music": ("A música está com você; eu fico no ritmo daqui.", "Que essa trilha combine com seu momento.", "Playlist rodando, Nova acompanhando.", "Uma pausa musical também vale.", "Dancinha opcional, concentração também."),
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
