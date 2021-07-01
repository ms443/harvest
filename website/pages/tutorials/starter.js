import NavBar from '../components/navbar.js'
import Header from '../components/header.js'
import CodeBlock from '../components/code.js'

import styles from '../../styles/Home.module.css'

export default function Module() {
  return (
    <div className={styles.container}>
      <Header title="Harvest | Tutorials"></Header>
      <NavBar></NavBar>
      <main className={styles.main}>
        <section>

        </section>
        <section className={styles.section}>
            <div className={styles.text}> 
                <h2>Prerequisites</h2>
                <p>As promised, there isn't too many prerequisites to 
                    start learning harvest. Just make sure you have the following:
                <ul>
                    <li>Python, version 3.8 or higher</li>
                    <li>A code editing software</li>
                    <li>Basic coding skills. Don't worry, if you've written anything more than 
                        'Hello World', you're good to go
                    </li>
                </ul>
                </p> 

                <h2>Installing</h2>
                <p>First things first, let's install the library. </p>
                
                <CodeBlock lang="bash" value="pip install -e git+https://github.com/tfukaza/harvest.git">
                </CodeBlock>
                
                <p>Next, we install additional libraries depending on which
                    broker you want to use. Harvest will do this automatically,
                    using the following command:
                </p>

                <CodeBlock lang="bash" value="pip install -e git+https://github.com/tfukaza/harvest.git#egg=harvest[BROKER]">
                </CodeBlock>

                <p>
                Where BROKER is replaced by one of the following brokers supported by Harvest:
              
                Robinhood
                On MacOS's zsh, you will need to use the following format instead:
                </p>

                <CodeBlock lang="bash" value="pip install -e 'git+https://github.com/tfukaza/harvest.git#egg=harvest[BROKER]'">
                </CodeBlock>
                
                <h2>Example Code</h2>
                <p>
                Once you have everything installed, we are ready to begin writing the code.
                For this example we will use Robinhood, but the code is still mostly the same
                if you decide to use other brokers. 
                
                Before we begin, there are three components of Harvest you need to know:

                <ul>
                    <li>Trader: The main module responsible for managing the other modules.</li>
                    <li>Broker: The module that communicates with the brokerage you are using.</li>
                    <li>Algo: The module where you define your algorithm.</li>
                </ul>

                We begin coding by import the aforementioned components, 
                or "modules" as they are called in Python.
                </p>

                <CodeBlock
                    lang="python"
                    value={`from harvest.algo import BaseAlgo
from harvest.trader import Trader
from harvest.broker.robinhood import RobinhoodBroker`}>
                </CodeBlock>

                First we create a Trader class

                if __name__ == "__main__":
                    t = Trader( RobinhoodBroker() )
                Few things happen here, and don't worry, this is as complex as Harvest will get (for now).

                The trader class is instantiated. Traders take two Brokers as input, a streamer and a broker. streamer is the broker used to retrieve stock/cryto data. broker is the brokerage used to place orders and manage your portfolio.
                For this example, we initialize RobinhoodBroker. The broker automatically reads the credentials saved in secret.yaml and sets up a connection with the broker.
                The Robinhood broker is specified as a streamer and will be used to get stock/crypto data.
                If the broker is unspecified, Robinhood will also be used as a broker.
                Fortunately after this, things get pretty easy. We specify what stock to track, in this case Twitter (TWTR).

                    t.add_symbol('TWTR')
                At this point, we define our algorithm. Algorithms are created by extending the BaseAlgo class.

                class Twitter(BaseAlgo):
                    def algo_init(self):
                        pass

                    def handler(self, meta):
                        pass
                Every also must define two functions

                algo_init: Function called right before the algorithm starts
                handler: Function called at a specified interval.
                In this example, we create a simple algorithm that buys and sells a single stock.
                <CodeBlock
                    lang="python"
                    value={`class Twitter(BaseAlgo):
    def algo_init(self):
        self.hold = False

    def handler(self, meta):
        if self.hold:
            self.sell('TWTR', 1)
            self.hold = False
        else:
            self.buy('TWTR', 1)
            self.hold = True`}
                        >
                </CodeBlock>
                
                Finally, we tell the trader to use this algorithm, and run it. Below is the final code after putting everything together.

                from harvest.algo import BaseAlgo
                from harvest.trader import Trader
                from harvest.broker.robinhood import RobinhoodBroker

                class Twitter(BaseAlgo):
                    def algo_init(self):
                        self.hold = False

                    def handler(self, meta):
                        if self.hold:
                            self.sell('TWTR', 1)    
                            self.hold = False
                        else:
                            self.buy('TWTR', 1)
                            self.hold = True

                if __name__ == "__main__":
                    t = Trader( RobinhoodBroker(), None )
                    t.add_symbol('TWTR')
                    t.set_algo(Twitter())
                    t.run(interval='1DAY')
                By specifying interval='1DAY' in run, the _handler will be called once every day.

                Now you can log into Robinhood on your phone or computer, and watch Harvest automatically buy and sell Twitter stocks!

                For more examples, check out the sample codes in the example folder.
            </div>
         
        </section>
    </main>

    <footer className={styles.footer}>
        
    </footer>
    </div>
  )
}
