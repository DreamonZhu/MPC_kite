import numpy as np
import matplotlib.pyplot as plt 
import matplotlib as mpl 
from casadi import *
from casadi.tools import *
import matplotlib._color_data as mcd
from orthogonal_collocation import Orthogonal_collocation_MPC
import math


#Simulation parameters
N_sim = 200
N = 50
dt = 0.2

#System Parameters
E0 = 5 # MX.sym("E0")
vm = 10 # MX.sym("vm")
vA = 0.5 #1 # MX.sym("vA")
vf = 0.1 # MX.sym("vf")
voff = np.pi # MX.sym("voff")
c = 0.028 # MX.sym("c")
beta = 0 # MX.sym("beta")
rho = 1 # MX.sym("rho")
L = 300 # MX.sym("l")
A = 160 # MX.sym("A")
hmin = 100

nx = 3
nu = 1

x = SX.sym("x", nx, 1)
u = SX.sym("u", nu, 1)
u_old = SX.sym("u_old", nu, 1)
t = SX.sym("t")

#Equations
v0 = vm + vA*sin(2*np.pi*vf*t + voff)
v0_fcn = Function('v0_fcn', [t], [v0])
E = E0 - c*(u**2)
E_fcn = Function('E_fcn', [u], [E])
va = v0_fcn(t)*E*cos(x[0])
#va = vm*E*cos(x[0])
va_fcn = Function('va_fcn', [x, t], [va])
PD = rho*(v0_fcn(t)**2)/2
PD_fcn = Function('PD_fcn', [t], [PD])
TF = PD_fcn(t)*A*(cos(x[0])**2)*(E_fcn(u) + 1)*np.sqrt(E_fcn(u)**2 + 1)*(cos(x[0])*cos(beta) + sin(x[0])*sin(beta)*sin(x[1]))
tension = Function('tension', [x,u,t], [TF])

height = L*cos(x[1])*sin(x[0])
height_fcn = Function('height_fcn', [x], [height])

xdot = vertcat((va_fcn(x, t)/L)*(cos(x[2]) - tan(x[0])/E_fcn(u)), 
-va_fcn(x, t)*sin(x[2])/(L*sin(x[0])), 
va_fcn(x,t)*u/L - cos(x[0])*(va_fcn(x, t)*sin(x[2])/(L*sin(x[0]))))



# alternative way of writing?
#xdot = vertcat((va_fcn(x, t)/L)*(cos(x[2]) - tan(x[0])/E_fcn(u)), 
#-va_fcn(x, t)*sin(x[2])/(L*sin(x[0])), 
#va_fcn(x,t)*u/L + cos(x[0])*xdot[1])

# System and numerical integration
system = Function('sys', [x,u,t], [xdot])
ode = {'x': x, 'ode': xdot, 'p': vertcat(u,t)}
opts = {'tf': dt}
ode_solver = integrator('F', 'idas', ode, opts)

def get_solver():
    return ode_solver

## Lagrange polynomials

# Computes L_j(tau) for a given list of collocation points
def Lgr(tau_col, tau, j):
    L_j = 1
    for k in range(len(tau_col)):
        if k!=j:
            L_j *= (tau-tau_col[k])/(tau_col[j]-tau_col[k])
    return L_j

# Evaluates x_i^K(t)
def LgrInter(tau_col, tau, xk):
    xk_i = 0
    for j in range(len(xk)):
        xk_i += Lgr(tau_col, tau, j)*xk[j, :]
    return xk_i


# collocation degree
#K = 3

#cost
wF = 1e-4
wu = 0.5

stage_cost = -wF*tension(x,u,t) + wu*((u - u_old)**2)
stage_cost_fcn = Function('stage_cost_fcn', [x, u, t, u_old], [stage_cost])

#state_constraints
#TODO: do something with constraint for psi
lb_x = np.array([0,-np.pi/2, -np.pi])
ub_x = np.array([np.pi/2,np.pi/2, np.pi])

lb_u = np.array([-10])
ub_u = np.array([10])


#For plotting
fig, ax = plt.subplots(3,2, figsize=(15,18))
fig.suptitle("Orthogonal collocation for all K's, N's and collocation points")
ax[0][0].set_title("Position of kite")
ax[1][0].set_title("Control input")
ax[2][0].set_title("Mean cost")


#size=3*2*8
plotcolors = []
for color in mcd.XKCD_COLORS:
    plotcolors = plotcolors + [color]
color_index=0

for K in range(2,6):

    # collocation points
    tau_cols = [collocation_points(K, 'radau')]
    tau_cols.append(collocation_points(K, 'legendre'))
    #tau_col = collocation_points(K, 'radau')
    #tau_col = collocation_points(K, 'legendre')
    for tc in range (len(tau_cols)):
        tau_col = tau_cols[tc]
        tau_col = [0]+tau_col

        tau_col_str=""
        if tc == 0:
            tau_col_str = "radau"
        else:
            tau_col_str = "legendre"

        # Orthogonal collocation coefficients
        tau = SX.sym("tau")
        A = np.zeros((K+1,K+1))
        for j in range(K+1):
            dLj = gradient(Lgr(tau_col, tau, j), tau)
            dLj_fcn = Function('dLj_fcn', [tau], [dLj])
            for k in range(K+1):
                A[j][k] = dLj_fcn(tau_col[k])

        # Continuity coefficients
        #to determine final state in each finite element

        D = np.zeros((K+1, 1))

        for j in range(K+1):
            L_j = Lgr(tau_col, tau, j)
            L_j_fcn = Function('L_j_fcn', [tau], [L_j])
            D[j] = L_j_fcn(1)



        ##  MPC loop
        #prediction horizon
        for N in range (50, 61, 10):
            
            #optimization variables

            opt_x = struct_symSX([
                entry('x', shape=nx, repeat=[N+1, K+1]),
                entry('u', shape=nu, repeat=[N])
            ])

            #time = np.array(np.linspace(dt, N_sim*dt, N_sim))


            lb_opt_x = opt_x(0)
            ub_opt_x = opt_x(0)

            lb_opt_x['x'] = lb_x
            ub_opt_x['x'] = ub_x

            lb_opt_x['u'] = lb_u
            ub_opt_x['u'] = ub_u

            #formulate optimization problem

            J = 0
            g = []
            lb_g = []
            ub_g = []

            x_init = SX.sym('x_init', nx)
            time = SX.sym('time', N) #or use t?

            x0 = opt_x['x', 0, 0]
            u_prev = opt_x['u', 0]

            g.append(x0-x_init)
            lb_g.append(np.zeros((nx,1)))
            ub_g.append(np.zeros((nx,1)))

                # objective
            for i in range(N):
                J += stage_cost_fcn(opt_x['x',i,0], opt_x['u',i], time[i], u_prev)
                
                # equality constraints (system equation)
                for k in range(1,K+1):
                    gk = -dt*system(opt_x['x',i,k], opt_x['u',i], time[i])
                    for j in range(K+1):
                        gk += A[j,k]*opt_x['x',i,j]
                        
                    
                    g.append(gk)
                    lb_g.append(np.zeros((nx,1)))
                    ub_g.append(np.zeros((nx,1)))   

                #inequality constraints
                ineq = height_fcn(opt_x['x', i, 0])
                #ineq = L*cos(opt_x['x', i, 0, 1])*sin(opt_x['x', i, 0, 0])
                g.append(ineq)
                lb_g.append(hmin)
                ub_g.append(L)
                
                x_next = horzcat(*opt_x['x',i])@D
                g.append(x_next - opt_x['x', i+1, 0])
                lb_g.append(np.zeros((nx,1)))
                ub_g.append(np.zeros((nx,1)))
                u_prev = opt_x['u', i]
                

            #J += terminal_cost_fcn(opt_x['x', N, 0])

            g = vertcat(*g)
            lb_g = vertcat(*lb_g)
            ub_g = vertcat(*ub_g)

            prob = {'f':J,'x':vertcat(opt_x),'g':g, 'p':vertcat(x_init, time)}
            mpc_solver = nlpsol('solver','ipopt',prob)

            print("g shape:", g.shape)
            print("lb_g shape:", lb_g.shape)
            print("ub_g shape:", ub_g.shape)
            #print(horzcat(g, lb_g, ub_g))
            # MPC Main loop

            #initialize
            x_0 = np.array([np.pi/4, np.pi/4, 0]).reshape(nx, 1)
            t_k = np.array(np.linspace(0, (N_sim+N)*dt, N_sim+N+1))
            res_x_mpc = [x_0]
            res_u_mpc = []
            costs =[]


            for i in range(N_sim):
                # solve optimization problem
                mpc_res = mpc_solver(p=vertcat(x_0, t_k[i:N+i]), lbg=lb_g, ubg=ub_g, lbx = lb_opt_x, ubx = ub_opt_x)
                
                # optionally: Warmstart the optimizer by passing the previous solution as an initial guess!
                if i>0:
                    #mpc_res = mpc_solver(p=x_0, x0=opt_x_k, lbg=0, ubg=0, lbx = lb_opt_x, ubx = ub_opt_x)
                    mpc_res = mpc_solver(p=vertcat(x_0, t_k[i:N+i]),x0=opt_x_k, lbg=lb_g, ubg=ub_g, lbx = lb_opt_x, ubx = ub_opt_x)

                    
                #extract cost
                cost_k = mpc_res['f']
                costs.append(cost_k)

                # Extract the control input
                opt_x_k = opt_x(mpc_res['x'])
                u_k = opt_x_k['u',0]

                # simulate the system
                res_integrator = ode_solver(x0=x_0, p=vertcat(u_k, t_k[i]))
                x_next = res_integrator['xf']
                
                # Update the initial state
                x_0 = x_next
                
                # Store the results
                res_x_mpc.append(x_next)
                res_u_mpc.append(u_k)
                

            # Make an array from the list of arrays:
            res_x_mpc = np.concatenate(res_x_mpc,axis=1)
            res_u_mpc = np.concatenate(res_u_mpc, axis=1)

            costs = np.concatenate(costs, axis=1)


def test_orth_col(dt = 0.2, Kmin=3, Kmax=3, Nmin=20, Nmax=20, N_sim=100, point_type='legendre', figname = 'orth_coll_all'):

    #For record keeping.
    min_avg_cost = 0
    min_cost_fluctuation = 100000
    K_min_avg_cost = 0
    N_min_avg_cost = 0
    col_points_min_avg = ""
    K_min_fluctuation = 0
    N_min_fluctuation = 0
    col_points_min_fluctuation = ""
    x_min_avg_cost = np.zeros((1,1))
    u_min_avg_cost = np.zeros((1,1))
    x_min_fluctuation = np.zeros((1,1))
    u_min_fluctuation = np.zeros((1,1))

    #For plotting
    fig, ax = plt.subplots(3,4, figsize=(28,15))
    fig.suptitle("Orthogonal collocation for all K's, N's and collocation points")
    ax[0][0].set_title("Position of kite")
    ax[1][0].set_title("Control input")
    ax[2][0].set_title("Mean cost")


    #size=3*2*8
    plotcolors = []
    for color in mcd.XKCD_COLORS:
        plotcolors = plotcolors + [color]
    color_index=0
    #K = 3
    for K in range(Kmin,Kmax+1):
        #dt = dt*faktor
        # collocation points
        tau_cols=[]
        if point_type == 'both':
            tau_cols = [collocation_points(K, 'radau')]
            tau_cols.append(collocation_points(K, 'legendre'))
        elif point_type == 'legendre' or point_type == 'radau':
            tau_cols = [collocation_points(K, point_type)]
        #tau_col = collocation_points(K, 'radau')
        #tau_col = collocation_points(K, 'legendre')
        for tc in range (len(tau_cols)):
            tau_col = tau_cols[tc]
            tau_col = [0]+tau_col

            tau_col_str=""
            if tc == 0:
                tau_col_str = "radau"
            else:
                tau_col_str = "legendre"

            for N in range(Nmin, Nmax+1, 10):
                res_x_mpc, res_u_mpc, costs, solve_times = Orthogonal_collocation_MPC(K=K, N=N, N_sim=N_sim, dt=dt, collocation_tech=tau_col_str)

                figk, axk = plt.subplots(3,3, figsize=(21,15))
                
                costs_mean = np.mean(costs)
                if costs_mean < min_avg_cost:
                    min_avg_cost = costs_mean
                    K_min_avg_cost = K
                    N_min_avg_cost = N
                    x_min_avg_cost = res_x_mpc
                    u_min_avg_cost = res_u_mpc
                    col_points_min_avg = tau_col_str
                
                if (math.fabs(np.max(costs)-costs_mean) + (math.fabs(costs_mean - np.min(costs)))) < min_cost_fluctuation:
                    min_cost_fluctuation = math.fabs(np.max(costs)-costs_mean) + (math.fabs(costs_mean - np.min(costs)))
                    K_min_fluctuation = K
                    N_min_fluctuation = N
                    x_min_fluctuation = res_x_mpc
                    u_min_fluctuation = res_u_mpc
                    col_points_min_fluctuation = tau_col_str

                tsol_mean = np.mean(solve_times)
                tsol_max = np.max(solve_times)


                ## PLOTTING
                #plot position
                ax[0][0].plot(L*sin(res_x_mpc[0].T)*sin(res_x_mpc[1].T), L*sin(res_x_mpc[0].T)*cos(res_x_mpc[1].T), label = 'K='+str(K)+', N='+str(N)+', col_points='+tau_col_str, color = plotcolors[color_index])

                axk[0][0].plot(L*sin(res_x_mpc[0].T)*sin(res_x_mpc[1].T), L*sin(res_x_mpc[0].T)*cos(res_x_mpc[1].T))
                axk[0][0].set_title("Position of kite, x and y")

                # plot the input
                ax[1][0].plot(res_u_mpc.T, label = 'K='+str(K)+', N='+str(N)+', col_points='+tau_col_str, color = plotcolors[color_index])
                
                axk[1][0].plot(res_u_mpc.T)
                axk[1][0].set_title("Control input")

                #plot angles over time
                ax[0][1].plot(res_x_mpc[0].T, label = 'K='+str(K)+', N='+str(N)+', col_points='+tau_col_str, color = plotcolors[color_index])
                axk[0][1].plot(res_x_mpc[0].T)

                ax[1][1].plot(res_x_mpc[1].T, label = 'K='+str(K)+', N='+str(N)+', col_points='+tau_col_str, color = plotcolors[color_index])
                axk[1][1].plot(res_x_mpc[1].T)

                ax[2][1].plot(res_x_mpc[2].T, label = 'K='+str(K)+', N='+str(N)+', col_points='+tau_col_str, color = plotcolors[color_index])
                axk[2][1].plot(res_x_mpc[2].T)

                #plot wind
                #ax[2][1].plot(t_k, v0_fcn(t_k))

                #plot cost
                axk[0][2].plot(costs.T)
                axk[0][2].axhline(costs_mean)
                axk[0][2].set_xlabel('time['+str(dt)+'sec]')
                axk[0][2].set_ylabel('cost')
                axk[0][2].set_title("Cost at given time")

                ax[2][0].axhline(costs_mean, label = 'K='+str(K)+', N='+str(N)+', col_points='+tau_col_str, color = plotcolors[color_index])
                ax[2][0].set_ylabel('cost')

                #plot computational times
                axk[1][2].plot(solve_times)
                axk[1][2].set_xlabel('number of runs')
                axk[1][2].set_xlabel('time spent on runs [s]')
                axk[1][2].axhline(tsol_mean, label='mean runtime: ' + str('{0:.3g}'.format(tsol_mean)) + 's', color='k')
                axk[1][2].axhline(tsol_max, label='max runtime: ' + str('{0:.3g}'.format(tsol_max)) + 's', color='r')
                axk[1][2].legend()

                color_index+=1

                ax[0][0].set_ylabel('height')
                axk[0][0].set_ylabel('height')
                ax[0][0].set_xlabel('horizontal position')
                axk[0][0].set_xlabel('horizontal position')

                ax[1][0].set_ylabel('input[N]')
                ax[1][0].set_xlabel('time['+str(dt)+'sec]')

                axk[1][0].set_ylabel('input[N]')
                axk[1][0].set_xlabel('time['+str(dt)+'sec]')

                ax[0][1].set_ylabel('theta')
                axk[0][1].set_ylabel('theta')
                ax[0][1].set_xlabel('time['+str(dt)+'sec]')
                axk[0][1].set_xlabel('time['+str(dt)+'sec]')

                ax[1][1].set_ylabel('phi')
                axk[1][1].set_ylabel('phi')
                ax[1][1].set_xlabel('time['+str(dt)+'sec]')
                axk[1][1].set_xlabel('time['+str(dt)+'sec]')

                ax[2][1].set_ylabel('psi')
                axk[2][1].set_ylabel('psi')
                ax[2][1].set_xlabel('time['+str(dt)+'sec]')
                axk[2][1].set_xlabel('time['+str(dt)+'sec]')

                figk.suptitle("Orthogonal collocation with K="+str(K)+", N="+str(N)+", col points="+tau_col_str+", dt="+str(dt))

                figk.savefig("Plots/png/orth_col_K="+str(K)+"_N="+str(N)+"_col_points="+tau_col_str+"_dt="+str(dt)+".png")
                figk.savefig("Plots/eps/orth_col_K="+str(K)+"_N="+str(N)+"_col_points="+tau_col_str+"_dt="+str(dt)+".eps")


    #plot best solutions with regard to cost
    # lowest mean
    ax[0][2].plot(L*sin(x_min_avg_cost[0].T)*sin(x_min_avg_cost[1].T), L*sin(x_min_avg_cost[0].T)*cos(x_min_avg_cost[1].T), label = 'K_min_avg='+str(K_min_avg_cost)+', N_min_avg='+str(N_min_avg_cost)+', col_points='+col_points_min_avg, color = plotcolors[color_index])
    ax[1][2].plot(u_min_avg_cost.T, label = 'K_min_avg='+str(K_min_avg_cost)+', N_min_avg='+str(N_min_avg_cost)+', col_points='+col_points_min_avg, color = plotcolors[color_index])
    ax[2][2].axhline(min_avg_cost, label = 'K_min_avg='+str(K_min_avg_cost)+', N_min_avg='+str(N_min_avg_cost)+', col_points='+col_points_min_avg, color = plotcolors[color_index])

    ax[0][2].set_title("Trajectory with lowest avg cost")
    ax[0][2].set_xlabel("Horizontal position")
    ax[0][2].set_ylabel("Height")
    ax[0][2].set_ylim(90, 220)
    ax[0][2].legend(loc='upper center')

    ax[1][2].set_title("Control input with lowest avg cost")
    ax[1][2].set_ylabel("Input [N]")
    ax[1][2].set_xlabel('time['+str(dt)+'sec]')
    ax[1][2].set_ylim(-12, 12)
    ax[1][2].legend(loc='upper center')


    ax[2][2].set_title("Lowest avg cost")
    ax[2][2].set_ylabel("cost")
    ax[2][2].legend()

    color_index+=1
    #least fluctuation
    ax[0][3].plot(L*sin(x_min_fluctuation[0].T)*sin(x_min_fluctuation[1].T), L*sin(x_min_fluctuation[0].T)*cos(x_min_fluctuation[1].T), label = 'K least fluctuation='+str(K_min_fluctuation)+', N least fluctuation='+str(N_min_fluctuation)+', col_points='+col_points_min_fluctuation, color = plotcolors[color_index])
    ax[1][3].plot(u_min_fluctuation.T, label = 'K least fluctuation='+str(K_min_fluctuation)+', N least fluctuation='+str(N_min_fluctuation)+', col_points='+col_points_min_fluctuation, color = plotcolors[color_index])
    ax[2][3].axhline(min_avg_cost, label = 'K least fluctuation='+str(K_min_fluctuation)+', N least fluctuation='+str(N_min_fluctuation)+', col_points='+col_points_min_fluctuation, color = plotcolors[color_index])

    ax[0][3].set_title("Trajectory with least fluctuating cost")
    ax[0][3].set_xlabel("Horizontal position")
    ax[0][3].set_ylabel("Height")
    ax[0][3].set_ylim(90, 220)
    ax[0][3].legend(loc='upper center')

    ax[1][3].set_title("Control input with least fluctuating cost")
    ax[1][3].set_ylabel("Input [N]")
    ax[1][3].set_xlabel('time['+str(dt)+'sec]')
    ax[1][3].set_ylim(-12, 12)
    ax[1][3].legend(loc='upper center')

    ax[2][3].set_title("Maximum deviation from min cost to max cost")
    ax[2][3].set_ylabel("cost")
    ax[2][3].legend()
    

    #fig.savefig("Plots/png/orth_col_opt_cost_dt="+str(dt)+".png")
    #fig.savefig("Plots/eps/orth_col_opt_dt="+str(dt)+".eps")

    fig.savefig("Plots/png/"+figname+".png")
    fig.savefig("Plots/eps/"+figname+".eps")

    ax[0][2].legend()
    ax[1][2].legend()
    ax[2][2].legend()
    ax[0][3].legend()
    ax[1][3].legend()
    ax[2][3].legend()

    #fig.savefig("Plots/png/orth_col_all_dt="+str(dt)+".png")
    #fig.savefig("Plots/eps/orth_col_all_dt="+str(dt)+".eps")
    fig.savefig("Plots/png/"+figname+".png")
    fig.savefig("Plots/eps/"+figname+".eps")

    

    #plt.show()