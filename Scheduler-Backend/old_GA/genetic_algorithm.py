import random
import copy
from old_GA.Chromosome import Chromosome
from old_GA.Gene import Gene
from utils import Utility
from old_GA.timetable import Timetable
from input_data import input_data
# from testclass import Testclass
class SchedulerMain:
    def __init__(self):
        self.firstlist = []
        self.newlist = []
        self.firstlistfitness = 0.0
        self.newlistfitness = 0.0
        self.populationsize = 1000
        self.maxgenerations = 100
        self.finalson = None

        # Printing input data (on console for testing)
        Utility.print_input_data()

        # Timetable = Timetable
        # timetable_instance = Timetable()
        # print(timetable_instance)

        # Printing slots (testing purpose only)
        Utility.print_slots()

        # Initializing first generation of chromosomes and putting in first list
        self.initialise_population()

        # Generating newer generations of chromosomes using crossovers and mutation
        self.create_new_generations()

    def create_new_generations(self):
        father = None
        mother = None
        son = None

        nogenerations = 0

        # Looping max no of generations times or until a suitable chromosome is found
        while nogenerations < self.maxgenerations:
            self.newlist = []
            self.newlistfitness = 0
            i = 0

            # Elitisim: best-performing chromosomes are carried over unchanged to the next generation.
            # therefore, first 10% of the population added to the new population as is
            for i in range(self.populationsize // 10):
                self.newlist.append(copy.deepcopy(self.firstlist[i]))
                self.newlistfitness += self.firstlist[i].get_fitness()

            # Adding other members after performing crossover and mutation
            while i < self.populationsize:  # Looping through the population size but not looping through the actualy chromosomes?
                father = self.select_parent_roulette()
                mother = self.select_parent_roulette()

                # Crossover
                if random.random() < input_data.cross_over_rate:
                    son = self.crossover(father, mother)
                else:
                    son = father

                # print("before crossover: ", father.print_chromosome, mother.print_chromosome)

                # Mutation
                if random.random() < input_data.mutation_rate:
                    son = self.custom_mutation(son)

                # self.custom_mutation(son)

                if son.fitness == 1:
                    print("Selected Chromosome is:-")
                    son.print_chromosome()
                    break

                self.newlist.append(son)
                self.newlistfitness += son.get_fitness()
                i += 1

            # If chromosome with fitness 1 is found
            if i < self.populationsize:
                print("****************************************************************************************")
                print(f"\n\nSuitable Timetable has been generated in the {i}th Chromosome of {nogenerations + 2} generation with fitness 1.")
                print("\nGenerated Timetable is:")
                son.print_time_table()
                self.finalson = son
                break

            # If chromosome with required fitness is not found in this generation
            self.firstlist = self.newlist
            self.firstlist.sort()
            self.newlist.sort()
            print(f"**************************     Generation {nogenerations + 2}     ********************************************\n")
            self.print_generation(self.newlist)
            nogenerations += 1


    def select_parent_roulette(self):
        self.firstlistfitness /= 10
        randomdouble = random.random() * self.firstlistfitness
        currentsum = 0
        i = 0

        while currentsum <= randomdouble:
            currentsum += self.firstlist[i].get_fitness()
            i += 1
        return copy.deepcopy(self.firstlist[i - 1])

    def custom_mutation(self, c):
        newfitness = 0
        oldfitness = c.get_fitness()
        geneno = random.randint(0, input_data.nostudentgroup - 1)

        i = 0
        while newfitness < oldfitness:
            c.gene[geneno] = Gene(geneno)
            # print(c.gene[0].room_assignment)
            newfitness = c.get_fitness()
            i += 1
            if i >= 500000:
                break
        return c

    def crossover(self, father, mother):
        randomint = random.randint(0, input_data.nostudentgroup - 1)
        temp = copy.deepcopy(father.gene[randomint])
        father.gene[randomint] = copy.deepcopy(mother.gene[randomint])
        mother.gene[randomint] = temp
        return father if father.get_fitness() > mother.get_fitness() else mother

    def initialise_population(self):
        self.firstlist = []
        self.firstlistfitness = 0

        for i in range(self.populationsize):
            c = Chromosome()
            self.firstlist.append(c)
            self.firstlistfitness += c.fitness

        self.firstlist.sort() # Sorting the chromosomes based on fitness 
        print(self.firstlist[0:2])
        print("----------Initial Generation-----------\n")
        self.print_generation(self.firstlist)

    def print_generation(self, gen_list):
        print("Fetching details from this generation...\n")

        # To print only initial 4 chromosomes of sorted list
        for i in range(4):
            print(f"Fitness of Chromosome no. {i}: {gen_list[i].get_fitness()}")
            gen_list[i].print_chromosome()
            print("")

        print(f"Chromosome no. {self.populationsize // 10 + 1} : {gen_list[self.populationsize // 10 + 1].get_fitness()}\n")
        print(f"Chromosome no. {self.populationsize // 5 + 1} : {gen_list[self.populationsize // 5 + 1].get_fitness()}\n")
        print(f"Most fit chromosome from this generation has fitness = {gen_list[0].get_fitness()}\n")

    def select_parent_best(self, gen_list):
        randomint = random.randint(0, 99)
        return copy.deepcopy(gen_list[randomint])

# ------ not in use ------
    def mutation(self, c):
        # shifting the slotno array of a gene to the left in a bid to rearrange
        geneno = random.randint(0, input_data.nostudentgroup - 1)
        temp = c.gene[geneno].slotno[0]
        for i in range(input_data.daysperweek * input_data.hoursperday - 1):
            c.gene[geneno].slotno[i] = c.gene[geneno].slotno[i + 1]
        c.gene[geneno].slotno[input_data.daysperweek * input_data.hoursperday - 1] = temp

    def swap_mutation(self, c):
        # swapping two slotno elements in a bid to rearrange a gene.slotno
        geneno = random.randint(0, input_data.nostudentgroup - 1)
        slotno1 = random.randint(0, input_data.hoursperday * input_data.daysperweek - 1)
        slotno2 = random.randint(0, input_data.hoursperday * input_data.daysperweek - 1)

        temp = c.gene[geneno].slotno[slotno1]
        c.gene[geneno].slotno[slotno1] = c.gene[geneno].slotno[slotno2]
        c.gene[geneno].slotno[slotno2] = temp


if __name__ == "__main__":
    SchedulerMain()
